"""Validated inputs and atomic config writes for the VPS HTTPS installer."""
from __future__ import annotations
import argparse
import ipaddress
import os
from pathlib import Path
import re
import socket
import tempfile
from urllib.request import urlopen


def public_ipv4(value):
    address=ipaddress.ip_address(value.strip())
    if address.version!=4 or not address.is_global:
        raise ValueError('A public IPv4 address is required.')
    return str(address)


def hostname(value):
    value=value.strip().lower()
    labels=value.split('.')
    if len(value)>253 or len(labels)<2 or value.endswith('.') or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',p) for p in labels):
        raise ValueError('Use a DNS hostname without a scheme, path or port.')
    try:ipaddress.ip_address(value)
    except ValueError:return value
    raise ValueError('Use a DNS hostname rather than a bare IP.')


def detect_ipv4():
    connection=os.environ.get('SSH_CONNECTION','').split()
    if len(connection)==4:
        try:return public_ipv4(connection[2])
        except ValueError:pass
    with urlopen('https://api.ipify.org',timeout=12) as response:
        return public_ipv4(response.read(128).decode('ascii'))


def choose_host(name='',address=''):
    if name:return hostname(name)
    address=public_ipv4(address) if address else detect_ipv4()
    name='futarchist-'+address.replace('.','-')+'.sslip.io'
    resolved={r[4][0] for r in socket.getaddrinfo(name,443,socket.AF_INET,socket.SOCK_STREAM)}
    if address not in resolved:raise ValueError('The generated hostname does not resolve to this public IP.')
    return name


def set_origin(path,value):
    """Preserve every unrelated value, permissions and ownership."""
    value='https://'+hostname(value.removeprefix('https://'))
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('The env file must be a regular file.')
    stat=path.stat();original=path.read_bytes();lines=original.splitlines(keepends=True)
    ending=b'\r\n' if b'\r\n' in original else b'\n'
    replacement=b'APP_URL='+value.encode('ascii')+ending
    output=[];found=False
    for line in lines:
        if line.strip().startswith(b'APP_URL='):
            if found:raise ValueError('Duplicate APP_URL entries must be reviewed before setup.')
            output.append(replacement);found=True
        else:output.append(line)
    if not found:
        if output and not output[-1].endswith(b'\n'):output[-1]+=ending
        output.append(replacement)
    fd,temporary=tempfile.mkstemp(prefix='.web-env-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),stat.st_mode&0o777)
            if os.geteuid()==0:os.fchown(stream.fileno(),stat.st_uid,stat.st_gid)
            stream.write(b''.join(output));stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return value


def main():
    parser=argparse.ArgumentParser(description='Prepare a validated FUTARCHIST web address')
    parser.add_argument('action',choices=('host','origin'))
    parser.add_argument('--hostname',default='');parser.add_argument('--ip',default='');parser.add_argument('--env',default='.env')
    args=parser.parse_args()
    try:
        print(choose_host(args.hostname,args.ip) if args.action=='host' else set_origin(args.env,args.hostname))
    except (OSError,ValueError) as error:
        parser.exit(1,'Web setup input check failed: '+str(error)+'\n')


if __name__=='__main__':main()
