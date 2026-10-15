#!/usr/bin/env python3
"""Local grid icon using the existing plugin PNG convention; no dependencies."""
import binascii
import struct
import sys
import zlib

size=300
def pixel(x,y):
    cx,cy=min(max(x,58),size-58),min(max(y,58),size-58)
    if (x-cx)**2+(y-cy)**2>58**2: return (0,0,0,0)
    t=(x+y)/(size*2)
    color=tuple(round(a*(1-t)+b*t) for a,b in zip((83,132,240),(43,72,168)))
    # Terminal chevron and cursor, aligned with the common NAS icon family.
    if 72<=x<=123 and (abs(y-(x+36))<9 or abs(y-(264-x))<9):return (255,255,255,255)
    if 143<=x<=226 and 180<=y<=196:return (255,255,255,255)
    return (*color,255)
def chunk(kind,data): return struct.pack('>I',len(data))+kind+data+struct.pack('>I',binascii.crc32(kind+data)&0xffffffff)
raw=bytearray()
for y in range(size):
    raw.append(0)
    for x in range(size): raw.extend(pixel(x+.5,y+.5))
with open(sys.argv[1],'wb') as output:
    output.write(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(bytes(raw),9))+chunk(b'IEND',b''))
