#!/usr/bin/env python3
"""Create VM with Flask app, firewall, and print URL."""

import argparse
import time

import google.auth
import googleapiclient.discovery

credentials, project = google.auth.default()
service = googleapiclient.discovery.build('compute', 'v1', credentials=credentials)

ZONE = 'us-west1-b'
FIREWALL_RULE = 'allow-5000'


def wait_op(compute, project, zone, op_name, global_op=False):
    get_op = compute.globalOperations().get if global_op else compute.zoneOperations().get
    kwargs = {'project': project, 'operation': op_name}
    if not global_op:
        kwargs['zone'] = zone
    while True:
        r = get_op(**kwargs).execute()
        if r['status'] == 'DONE':
            if 'error' in r:
                raise Exception(r['error'])
            return r
        time.sleep(1)


def ensure_firewall(compute, project):
    try:
        compute.firewalls().get(project=project, firewall=FIREWALL_RULE).execute()
        return
    except Exception:
        pass
    body = {
        'name': FIREWALL_RULE,
        'network': f'projects/{project}/global/networks/default',
        'direction': 'INGRESS',
        'sourceRanges': ['0.0.0.0/0'],
        'targetTags': [FIREWALL_RULE],
        'allowed': [{'IPProtocol': 'tcp', 'ports': ['5000']}],
    }
    op = compute.firewalls().insert(project=project, body=body).execute()
    wait_op(compute, project, ZONE, op['name'], global_op=True)


def create_instance(compute, project, zone, name, machine_type='f1-micro'):
    startup = '''#!/bin/bash
set -e
cd /root
apt-get update -y && apt-get install -y python3 python3-pip git
git clone https://github.com/cu-csci-4253-datacenter/flask-tutorial
cd flask-tutorial && python3 setup.py install && pip3 install -e .
export FLASK_APP=flaskr && flask init-db
nohup flask run -h 0.0.0.0 &
'''
    img = compute.images().getFromFamily(project='ubuntu-os-cloud', family='ubuntu-2204-lts').execute()
    config = {
        'name': name,
        'machineType': f'zones/{zone}/machineTypes/{machine_type}',
        'disks': [{'boot': True, 'autoDelete': True, 'initializeParams': {'sourceImage': img['selfLink']}}],
        'networkInterfaces': [{'network': 'global/networks/default', 'accessConfigs': [{'type': 'ONE_TO_ONE_NAT', 'name': 'External NAT'}]}],
        'metadata': {'items': [{'key': 'startup-script', 'value': startup}]},
    }
    op = compute.instances().insert(project=project, zone=zone, body=config).execute()
    wait_op(compute, project, zone, op['name'])

    inst = compute.instances().get(project=project, zone=zone, instance=name).execute()
    op2 = compute.instances().setTags(project=project, zone=zone, instance=name,
        body={'items': [FIREWALL_RULE], 'fingerprint': inst.get('tags', {}).get('fingerprint', '')}).execute()
    wait_op(compute, project, zone, op2['name'])

    inst = compute.instances().get(project=project, zone=zone, instance=name).execute()
    ip = next((ac.get('natIP') for ac in inst.get('networkInterfaces', [{}])[0].get('accessConfigs', []) if ac.get('type') == 'ONE_TO_ONE_NAT'), None)
    print(f"\nVisit: http://{ip or 'pending'}:5000\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--name', default='flask-app-vm')
    p.add_argument('--zone', default=ZONE)
    p.add_argument('--machine-type', default='f1-micro')
    args = p.parse_args()
    ensure_firewall(service, project)
    create_instance(service, project, args.zone, args.name, args.machine_type)


if __name__ == '__main__':
    main()
