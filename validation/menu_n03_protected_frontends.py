import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--formal-state', type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.formal_state.read_text())
    protected = {}
    for key in ('historical_menu_f01', 'historical_menu_f01_rework', 'historical_menu_n02', 'historical_ui02', 'historical_mvp01'):
        expected = state[key]
        directory = ROOT / Path(expected['frontend_directory']).name
        manifest = digest(directory / 'asset-manifest.json')
        index = digest(directory / 'index.html')
        if manifest != expected['manifest_sha256'] or index != expected['index_sha256']:
            raise ValueError('既有用户体验制品摘要不符：' + key)
        protected[key] = {'directory': str(directory), 'manifest_sha256': manifest, 'index_sha256': index}
    output = ROOT / 'evidence/menu-delivery/N03/protected-frontends.json'
    output.write_text(json.dumps({'status': 'PASS', 'scope': 'MENU_N03_PROTECTED_FRONTENDS_ONLY', 'protected_frontends': protected, 'business_data_accessed': False, 'visual': 'NOT_RUN', 'user_acceptance': 'NOT_RUN'}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'protected_frontend_count': len(protected), 'report': str(output)}))


if __name__ == '__main__':
    main()
