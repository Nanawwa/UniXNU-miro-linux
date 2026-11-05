import socket, time, sys
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("0.0.0.0", 6666))
s.settimeout(600)
out = open(__import__("os").environ.get("NETCONSOLE_LOG", "netconsole.log"), "ab", buffering=0)
print("listening on 6666", flush=True)
end = time.time() + 900
while time.time() < end:
    try:
        data, addr = s.recvfrom(65535)
    except socket.timeout:
        continue
    ts = time.strftime("%H:%M:%S")
    for line in data.decode("utf-8", "replace").splitlines():
        out.write(f"[{ts}] {line}\n".encode())
print("listener done", flush=True)
