#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def validate(data):
    if not isinstance(data, dict) or not isinstance(data.get('nodes', []), list):
        raise ValueError('config nodes must be a list')
    ids = set()
    tokens = set()
    for index, node in enumerate(data.get('nodes', [])):
        if not isinstance(node, dict):
            raise ValueError(f'node {index} must be an object')
        for field in ('id', 'name', 'type'):
            if not isinstance(node.get(field), str) or not node[field].strip():
                raise ValueError(f'node {index} has invalid {field}')
        if node['id'] in ids:
            raise ValueError(f'duplicate node id: {node["id"]}')
        ids.add(node['id'])
        if node['type'] not in ('local', 'agent'):
            raise ValueError(f'node {node["id"]} has invalid type')
        if node['type'] == 'agent':
            token = node.get('token')
            if not isinstance(token, str) or not token.strip():
                raise ValueError(f'node {node["id"]} has invalid token')
            if token in tokens:
                raise ValueError('duplicate agent token')
            tokens.add(token)
    return data


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/vps-probe/config.json')
    validate(json.loads(path.read_text()))
    print(f'valid: {path}')


if __name__ == '__main__':
    main()
