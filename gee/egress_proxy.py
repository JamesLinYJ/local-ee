"""Minimal HTTPS CONNECT relay. No arbitrary HTTP forwarding; exact provider allowlist."""
import asyncio
import ipaddress
import socket
import os
from .sync import ALLOWED

async def pipe(reader,writer):
    try:
        while data:=await reader.read(65536):writer.write(data);await writer.drain()
    finally:
        writer.close()

async def handle(reader,writer):
    remote=None
    try:
        header=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),timeout=10)
        if len(header)>8192:raise ValueError('header size')
        method,target,_=header.split(b'\r\n',1)[0].decode('ascii').split(' ')
        host,port=target.rsplit(':',1)
        if method!='CONNECT' or port!='443' or host not in ALLOWED:raise ValueError('host not allowed')
        results=await asyncio.get_running_loop().getaddrinfo(host,443,type=socket.SOCK_STREAM)
        addresses=[r[4][0] for r in results]
        def permitted(address):
            ip=ipaddress.ip_address(address)
            # Opt-in for this Mac's DNS proxy, which returns benchmark-range fake IPs.
            # Only exact allowlisted TLS destinations reach this branch; RFC1918, loopback and link-local remain blocked.
            return ip.is_global or (os.environ.get('ALLOW_FAKEIP_DNS')=='1' and ip in ipaddress.ip_network('198.18.0.0/15'))
        if not addresses or any(not permitted(a) for a in addresses):raise ValueError('non-public destination')
        upstream,remote=await asyncio.wait_for(asyncio.open_connection(addresses[0],443),timeout=20)
        writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n');await writer.drain()
        # Only destination host, no path/query/token/body, is recorded locally.
        print('ALLOW '+host,flush=True)
        await asyncio.gather(pipe(reader,remote),pipe(upstream,writer))
    except Exception:
        try:writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n');await writer.drain()
        except Exception:pass
    finally:
        writer.close()
        if remote:remote.close()

async def main():
    server=await asyncio.start_server(handle,'0.0.0.0',3128,limit=8192)
    async with server:await server.serve_forever()
if __name__=='__main__':asyncio.run(main())
