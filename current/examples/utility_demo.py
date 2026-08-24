from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

from sedb.db import Database
from sedb.entities import EntityService
from sedb.fields import FieldService
from sedb.semantic import SemanticDedupService
from sedb.utility import UtilityService
from sedb.views import ViewService


def _future(days: int = 8) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat().replace('+00:00', 'Z')


def _reset(path: str | Path) -> Path:
    path = Path(path)
    if path.exists():
        path.unlink()
    return path


def build_utility_demo(path: str | Path) -> dict:
    path = _reset(path)
    db = Database(path)
    fields = FieldService(db)
    entities = EntityService(db)
    views = ViewService(db)
    semantic = SemanticDedupService(db)
    utility = UtilityService(db)

    entity_ids = [
        entities.create_entity(label=f'Record {index:02d}', kind='demo')['id']
        for index in range(10)
    ]

    created = {}
    for key, label in [
        ('fresh_empty', 'Fresh empty'),
        ('old_unused', 'Old unused'),
        ('protected_unused', 'Protected unused'),
        ('task_supported', 'Task supported'),
        ('source_quality', 'Source quality'),
        ('quality_source', 'Quality source'),
        ('reactivation_signal', 'Reactivation signal'),
    ]:
        created[key] = fields.create_field(key=key, label=label)

    utility.set_guardrail(
        'protected_unused', True,
        reason='Rare compliance dimension must remain available.',
        evaluator='demo:governance',
    )
    views.create_view('Utility protected task', ['task_supported'], query_text='demo')

    entities.set_cell(entity_ids[0], 'source_quality', 'verified', source='demo')
    semantic.scan_field_similarity(namespace='global', threshold=0.95, max_neighbors=6)

    fields.transition(
        created['reactivation_signal']['id'], 'converged',
        reason='Demo baseline convergence before new evidence.',
        evaluator='demo:governance',
    )
    time.sleep(0.002)
    entities.set_cell(entity_ids[0], 'reactivation_signal', True, source='demo:new-evidence')

    old_as_of = _future(8)
    assessments = {
        'fresh_empty': utility.assess_field('fresh_empty', evaluator='demo:utility'),
        'old_unused': utility.assess_field('old_unused', evaluator='demo:utility', as_of=old_as_of),
        'protected_unused': utility.assess_field('protected_unused', evaluator='demo:utility', as_of=old_as_of),
        'task_supported': utility.assess_field('task_supported', evaluator='demo:utility', as_of=old_as_of),
        'semantic_review': utility.assess_field('source_quality', evaluator='demo:utility', as_of=old_as_of),
        'reactivation_signal': utility.assess_field('reactivation_signal', evaluator='demo:utility'),
    }

    applied = utility.apply_assessment(
        assessments['old_unused']['id'],
        reason='Demo operator explicitly accepted the convergence recommendation.',
        evaluator='demo:operator',
    )

    with db.connect() as conn:
        lifecycle_links = int(
            conn.execute(
                "SELECT COUNT(*) FROM field_evaluations WHERE evidence_json LIKE ?",
                (f'%{assessments["old_unused"]["id"]}%',),
            ).fetchone()[0]
        )
        pending_semantic = int(
            conn.execute("SELECT COUNT(*) FROM semantic_candidates WHERE status='pending'").fetchone()[0]
        )

    return {
        'database': str(path),
        'entities': len(entity_ids),
        'fields': len(created),
        'recommendations': {key: value['recommendation'] for key, value in assessments.items()},
        'scores': {key: value['score'] for key, value in assessments.items()},
        'applied_old_unused_status': applied['field']['status'],
        'lifecycle_assessment_links': lifecycle_links,
        'pending_semantic_candidates': pending_semantic,
    }


def benchmark_utility_registry(path: str | Path, field_count: int = 10_000) -> dict:
    if field_count < 1:
        raise ValueError('field_count must be >= 1')
    path = _reset(path)
    db = Database(path)
    fields = FieldService(db)
    entities = EntityService(db)
    utility = UtilityService(db)

    fields.bulk_create_fields(
        {
            'key': f'utility_field_{index:05d}',
            'label': f'Utility field {index:05d}',
            'description': 'Synthetic registry field for bounded utility assessment validation.',
        }
        for index in range(field_count)
    )
    for index in range(3):
        entities.create_entity(label=f'Benchmark record {index + 1}', kind='benchmark')

    as_of = _future(8)
    start = time.perf_counter()
    assessments = utility.assess_registry(
        statuses=('active',),
        limit_fields=field_count,
        offset=0,
        evaluator='benchmark:utility-v1',
        as_of=as_of,
    )
    elapsed = time.perf_counter() - start
    recommendations = Counter(item['recommendation'] for item in assessments)

    return {
        'database': str(path),
        'fields': field_count,
        'entities': 3,
        'assessments': len(assessments),
        'limit_fields': field_count,
        'policy_version': assessments[0]['policy_version'] if assessments else 'utility-v1',
        'recommendations': dict(sorted(recommendations.items())),
        'elapsed_seconds': round(elapsed, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Build SEDB v0.3A field-utility demonstration data.')
    parser.add_argument('--db', default='sedb-utility-v0.3a.sqlite')
    parser.add_argument('--benchmark-db', default='sedb-utility-10k-v0.3a.sqlite')
    parser.add_argument('--fields', type=int, default=10_000)
    args = parser.parse_args()
    result = {
        'governance_demo': build_utility_demo(args.db),
        'registry_benchmark': benchmark_utility_registry(args.benchmark_db, args.fields),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
