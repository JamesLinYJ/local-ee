"""Do not execute a task before its supervisor has durably saved its identity."""
import os
import sys


def main():
    fd=int(sys.argv[1])
    ready=os.read(fd,1)
    os.close(fd)
    if ready!=b'1': raise SystemExit(1)
    os.execv(sys.argv[2],sys.argv[2:])


if __name__=='__main__': main()
