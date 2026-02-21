#!/usr/bin/env python3
"""Create VM-1 which creates VM-2 (Flask app) using service account credentials."""

import argparse
import json
import os
import time

import google.oauth2.service_account as service_account
import googleapiclient.discovery

CREDS_FILE = 'service-credentials.json'
if not os.path.isfile(CREDS_FILE):
    raise SystemExit(f"Missing {CREDS_FILE}. Create service account, grant Compute Admin, download JSON key.")
with open(CREDS_FILE) as f:
    _creds_data = json.load(f)
project = os.getenv('GOOGLE_CLOUD_PROJECT') or _creds_data.get('project_id')
if not project:
    raise SystemExit("Set GOOGLE_CLOUD_PROJECT or use credentials with project_id.")
credentials = service_account.Credentials.from_service_account_file(CREDS_FILE)
service = googleapiclient.discovery.build('compute', 'v1', credentials=credentials)

ZONE = 'us-west1-b'


def wait_op(compute, project, zone, op_name):
    while True:
        r = compute.zoneOperations().get(project=project, zone=zone, operation=op_name).execute()
        if r['status'] == 'DONE':
            if 'error' in r:
                raise Exception(r['error'])
            return r
        time.sleep(1)


VM1_LAUNCHER = r'''
import os, time
import google.oauth2.service_account as sa
import googleapiclient.discovery as disc
cred = sa.Credentials.from_service_account_file("/srv/service-credentials.json")
proj = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
if not proj: raise SystemExit("GOOGLE_CLOUD_PROJECT not set")
comp = disc.build("compute", "v1", credentials=cred)
zone = "us-west1-b"
with open("/srv/vm2-startup-script.sh") as f: script = f.read()
img = comp.images().getFromFamily(project="ubuntu-os-cloud", family="ubuntu-2204-lts").execute()
cfg = {
    "name": "flask-app-vm2",
    "machineType": "zones/%s/machineTypes/f1-micro" % zone,
    "disks": [{"boot": True, "autoDelete": True, "initializeParams": {"sourceImage": img["selfLink"]}}],
    "networkInterfaces": [{"network": "global/networks/default", "accessConfigs": [{"type": "ONE_TO_ONE_NAT", "name": "External NAT"}]}],
    "metadata": {"items": [{"key": "startup-script", "value": script}]},
    "tags": {"items": ["allow-5000"]},
}
op = comp.instances().insert(project=proj, zone=zone, body=cfg).execute()
while True:
    r = comp.zoneOperations().get(project=proj, zone=zone, operation=op["name"]).execute()
    if r["status"] == "DONE":
        if "error" in r: raise Exception(r["error"])
        break
    time.sleep(1)
inst = comp.instances().get(project=proj, zone=zone, instance="flask-app-vm2").execute()
ip = next((a.get("natIP") for a in inst["networkInterfaces"][0].get("accessConfigs", []) if a.get("type") == "ONE_TO_ONE_NAT"), None)
print("VM-2: http://%s:5000" % (ip or "pending"))
'''

VM2_SCRIPT = '''#!/bin/bash
set -e
cd /root
apt-get update -y && apt-get install -y python3 python3-pip git
git clone https://github.com/cu-csci-4253-datacenter/flask-tutorial
cd flask-tutorial && python3 setup.py install && pip3 install -e .
export FLASK_APP=flaskr && flask init-db
nohup flask run -h 0.0.0.0 &
'''

VM1_SCRIPT = '''#!/bin/bash
set -e
apt-get update -y && apt-get install -y python3 python3-pip
mkdir -p /srv && cd /srv
MD="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
curl -sH "Metadata-Flavor: Google" "$MD/vm2-startup-script" > vm2-startup-script.sh
curl -sH "Metadata-Flavor: Google" "$MD/service-credentials" > service-credentials.json
curl -sH "Metadata-Flavor: Google" "$MD/vm1-launch-vm2-code" > vm1-launch-vm2-code.py
export GOOGLE_CLOUD_PROJECT=$(curl -sH "Metadata-Flavor: Google" "$MD/project")
pip3 install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib
python3 vm1-launch-vm2-code.py
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--name', default='vm1-launcher')
    p.add_argument('--zone', default=ZONE)
    args = p.parse_args()

    with open(CREDS_FILE) as f:
        creds_json = f.read()

    img = service.images().getFromFamily(project='ubuntu-os-cloud', family='ubuntu-2204-lts').execute()
    meta = [
        {'key': 'startup-script', 'value': VM1_SCRIPT},
        {'key': 'vm2-startup-script', 'value': VM2_SCRIPT},
        {'key': 'service-credentials', 'value': creds_json},
        {'key': 'vm1-launch-vm2-code', 'value': VM1_LAUNCHER},
        {'key': 'project', 'value': project},
    ]
    config = {
        'name': args.name,
        'machineType': f'zones/{args.zone}/machineTypes/f1-micro',
        'disks': [{'boot': True, 'autoDelete': True, 'initializeParams': {'sourceImage': img['selfLink']}}],
        'networkInterfaces': [{'network': 'global/networks/default', 'accessConfigs': [{'type': 'ONE_TO_ONE_NAT', 'name': 'External NAT'}]}],
        'metadata': {'items': meta},
    }
    op = service.instances().insert(project=project, zone=args.zone, body=config).execute()
    wait_op(service, project, args.zone, op['name'])
    print("VM-1 created. Check serial console or SSH /srv for VM-2 URL.")


if __name__ == '__main__':
    main()
