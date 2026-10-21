import argparse
import getpass
from . import db,auth
parser=argparse.ArgumentParser()
parser.add_argument('command',choices=['user','role'])
parser.add_argument('name')
parser.add_argument('--role',choices=['admin','dataset_manager','researcher','viewer'])
args=parser.parse_args()
db.init()
if args.command=='role':
    if not args.role:parser.error('role requires --role')
    from .services.administration import user_update
    user_update(None,args.name,{'role':args.role})
    print('Role updated; old sessions revoked; audit recorded.')
else:
    auth.create_user(args.name,getpass.getpass('Password (12+ characters): '),role=args.role)
    print('User saved; old sessions revoked. Existing roles preserved.')
