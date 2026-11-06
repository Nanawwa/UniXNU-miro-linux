#!/usr/bin/env python3
import struct, sys
b = open(sys.argv[1], 'rb').read()
p = b[(len(b)//4096-9)*4096:(len(b)//4096-9)*4096+4096]
print(struct.unpack_from('<Q', p, 99)[0])
