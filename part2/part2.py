#!/usr/bin/env python3
"""Snapshot Part 1 instance disk, create image, create 3 instances, write TIMING.md."""

import argparse
import time

import google.auth
import googleapiclient.discovery

credentials, project = google.auth.default()
service = googleapiclient.discovery.build('compute', 'v1', credentials=credentials)

ZONE = 'us-west1-b'
TAG = 'allow-5000'


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


def get_boot_disk(compute, project, zone, instance):
    inst = compute.instances().get(project=project, zone=zone, instance=instance).execute()
    for d in inst.get('disks', []):
        if d.get('boot'):
            return d['source'].split('/')[-1]
    raise ValueError(f"No boot disk: {instance}")


def create_instance(compute, project, zone, name, image_link, machine_type='f1-micro'):
    config = {
        'name': name,
        'machineType': f'zones/{zone}/machineTypes/{machine_type}',
        'disks': [{'boot': True, 'autoDelete': True, 'initializeParams': {'sourceImage': image_link}}],
        'networkInterfaces': [{'network': 'global/networks/default', 'accessConfigs': [{'type': 'ONE_TO_ONE_NAT', 'name': 'External NAT'}]}],
        'tags': {'items': [TAG]},
    }
    op = compute.instances().insert(project=project, zone=zone, body=config).execute()
    wait_op(compute, project, zone, op['name'])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('instance_name')
    p.add_argument('--zone', default=ZONE)
    p.add_argument('--machine-type', default='f1-micro')
    args = p.parse_args()

    inst_name = args.instance_name
    disk = get_boot_disk(service, project, args.zone, inst_name)
    snapshot_name = f'base-snapshot-{inst_name}'
    image_name = f'base-image-{inst_name}'

    op = service.disks().createSnapshot(project=project, zone=args.zone, disk=disk, body={'name': snapshot_name}).execute()
    wait_op(service, project, args.zone, op['name'])
    snap = service.snapshots().get(project=project, snapshot=snapshot_name).execute()

    op = service.images().insert(project=project, body={'name': image_name, 'sourceSnapshot': snap['selfLink']}).execute()
    wait_op(service, project, args.zone, op['name'], global_op=True)
    img = service.images().get(project=project, image=image_name).execute()

    times = []
    for i in range(1, 4):
        name = f'{inst_name}-clone-{i}'
        start = time.perf_counter()
        create_instance(service, project, args.zone, name, img['selfLink'], args.machine_type)
        times.append((name, time.perf_counter() - start))

    with open('TIMING.md', 'w') as f:
        f.write("# Part 2 - Instance creation times\n\n| Instance | Time (s) |\n|----------|----------|\n")
        for name, t in times:
            f.write(f"| {name} | {t:.2f} |\n")


if __name__ == '__main__':
    main()
