/*
 * uvcreq — envoie des requêtes de contrôle UVC à une webcam USB sous macOS,
 * via IOKit (comme CameraController), sans accès exclusif ni droits root.
 *
 * Compilation : clang -O2 -o uvcreq uvcreq.c -framework IOKit -framework CoreFoundation
 *
 * Usage : uvcreq <vid> <pid>
 *   puis, sur l'entrée standard, une requête par ligne :
 *     <bmRequestType> <bRequest> <wValue> <wIndex> <wLength> [données hex]
 *   (nombres en hexadécimal). Réponse par ligne : "OK <hex>" ou "ERR <code>".
 *   wIndex : l'octet bas (numéro d'interface) est remplacé automatiquement
 *   par celui de l'interface VideoControl de la caméra.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/usb/IOUSBLib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static IOUSBInterfaceInterface **open_vc_interface(int vid, int pid, int *if_num) {
    CFMutableDictionaryRef match = IOServiceMatching("IOUSBHostDevice");
    CFNumberRef v = CFNumberCreate(NULL, kCFNumberIntType, &vid);
    CFNumberRef p = CFNumberCreate(NULL, kCFNumberIntType, &pid);
    CFDictionarySetValue(match, CFSTR(kUSBVendorID), v);
    CFDictionarySetValue(match, CFSTR(kUSBProductID), p);
    CFRelease(v);
    CFRelease(p);
    io_service_t dev_svc = IOServiceGetMatchingService(kIOMainPortDefault, match);
    if (!dev_svc) return NULL;

    IOCFPlugInInterface **plug = NULL;
    SInt32 score;
    if (IOCreatePlugInInterfaceForService(dev_svc, kIOUSBDeviceUserClientTypeID, kIOCFPlugInInterfaceID,
                                          &plug, &score) != kIOReturnSuccess || !plug) {
        IOObjectRelease(dev_svc);
        return NULL;
    }
    IOUSBDeviceInterface **dev = NULL;
    (*plug)->QueryInterface(plug, CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID), (LPVOID *)&dev);
    IODestroyPlugInInterface(plug);
    IOObjectRelease(dev_svc);
    if (!dev) return NULL;

    IOUSBFindInterfaceRequest req = {.bInterfaceClass = 0x0E, .bInterfaceSubClass = 0x01,
                                     .bInterfaceProtocol = kIOUSBFindInterfaceDontCare,
                                     .bAlternateSetting = kIOUSBFindInterfaceDontCare};
    io_iterator_t it;
    IOUSBInterfaceInterface **intf = NULL;
    if ((*dev)->CreateInterfaceIterator(dev, &req, &it) == kIOReturnSuccess) {
        io_service_t if_svc = IOIteratorNext(it);
        if (if_svc) {
            if (IOCreatePlugInInterfaceForService(if_svc, kIOUSBInterfaceUserClientTypeID,
                                                  kIOCFPlugInInterfaceID, &plug, &score) == kIOReturnSuccess && plug) {
                (*plug)->QueryInterface(plug, CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID), (LPVOID *)&intf);
                IODestroyPlugInInterface(plug);
            }
            IOObjectRelease(if_svc);
        }
        IOObjectRelease(it);
    }
    (*dev)->Release(dev);
    if (intf) {
        UInt8 n = 0;
        (*intf)->GetInterfaceNumber(intf, &n);
        *if_num = n;
    }
    return intf;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <vid hex> <pid hex>\n", argv[0]);
        return 2;
    }
    int vid = (int)strtol(argv[1], NULL, 16), pid = (int)strtol(argv[2], NULL, 16), if_num = 0;
    IOUSBInterfaceInterface **intf = open_vc_interface(vid, pid, &if_num);
    if (!intf) {
        printf("ERR nodevice\n");
        fflush(stdout);
        return 1;
    }
    printf("READY %d\n", if_num);
    fflush(stdout);

    char line[4096];
    while (fgets(line, sizeof line, stdin)) {
        unsigned rt, rq, val, idx, len;
        char hex[2048] = "";
        if (sscanf(line, "%x %x %x %x %x %2047s", &rt, &rq, &val, &idx, &len, hex) < 5) {
            printf("ERR parse\n");
            fflush(stdout);
            continue;
        }
        UInt8 buf[1024] = {0};
        if (len > sizeof buf) len = sizeof buf;
        for (size_t i = 0; hex[0] && i < len && hex[2 * i] && hex[2 * i + 1]; i++) {
            unsigned b;
            sscanf(&hex[2 * i], "%2x", &b);
            buf[i] = (UInt8)b;
        }
        IOUSBDevRequest r = {.bmRequestType = (UInt8)rt, .bRequest = (UInt8)rq, .wValue = (UInt16)val,
                             .wIndex = (UInt16)((idx & 0xFF00) | (if_num & 0xFF)), .wLength = (UInt16)len,
                             .pData = buf};
        IOReturn kr = (*intf)->ControlRequest(intf, 0, &r);
        if (kr != kIOReturnSuccess) {
            printf("ERR %08x\n", kr);
        } else {
            printf("OK ");
            for (UInt32 i = 0; i < r.wLenDone && (rt & 0x80); i++) printf("%02x", buf[i]);
            printf("\n");
        }
        fflush(stdout);
    }
    (*intf)->Release(intf);
    return 0;
}
