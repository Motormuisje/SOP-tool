"""Flask routes for material groups (named per-session material sets).

A group is pure VIEW metadata: it never touches the engine, the reset
baseline, replay or the global config. Activating a group only changes what
the read endpoints aggregate (see ui/scoping.py) — no rebuild, no recalc.
"""

import uuid
from datetime import datetime
from typing import Callable

from flask import Blueprint, jsonify, request

_ERR_NO_SESSION = 'Geen actieve sessie'
_ERR_NOT_FOUND = 'Groep niet gevonden'


def groups_payload(sess, engine) -> dict:
    """The groups + active-state block shared by GET and mutations."""
    groups = sess.get('material_groups') or {}
    known = set()
    data = getattr(engine, 'data', None)
    if data is not None:
        known = set(getattr(data, 'materials', {}) or {})
    out = []
    unknown_counts = {}
    for group in groups.values():
        materials = [str(m) for m in (group.get('materials') or [])]
        unknown = sum(1 for m in materials if known and m not in known)
        unknown_counts[group['id']] = unknown
        out.append({
            'id': group['id'],
            'name': group.get('name', ''),
            'materials': materials,
            'created_at': group.get('created_at', ''),
            'source': group.get('source', ''),
        })
    return {
        'groups': out,
        'active_group_id': sess.get('active_material_group'),
        'unknown_counts': unknown_counts,
    }


def prune_material_from_groups(sess: dict, material_number: str) -> None:
    """Drop a removed material (e.g. deleted dynamic product) from every group."""
    mn = str(material_number)
    for group in (sess.get('material_groups') or {}).values():
        group['materials'] = [m for m in (group.get('materials') or [])
                              if str(m) != mn]


def create_material_groups_blueprint(
    get_active: Callable[[], tuple],
    save_sessions_to_disk: Callable[[], None],
) -> Blueprint:
    bp = Blueprint('material_groups', __name__)

    def _sess_or_error():
        sess, engine = get_active()
        if sess is None:
            return None, None, (jsonify({'error': _ERR_NO_SESSION}), 400)
        sess.setdefault('material_groups', {})
        sess.setdefault('active_material_group', None)
        return sess, engine, None

    @bp.route('/api/material_groups', methods=['GET'])
    def list_groups():
        sess, engine, err = _sess_or_error()
        if err:
            return err
        return jsonify(groups_payload(sess, engine))

    @bp.route('/api/material_groups', methods=['POST'])
    def create_group():
        sess, engine, err = _sess_or_error()
        if err:
            return err
        body = request.get_json(force=True, silent=True) or {}
        name = str(body.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Naam mag niet leeg zijn.'}), 400
        raw = body.get('materials')
        if not isinstance(raw, list) or not raw:
            return jsonify({'error': 'Een groep heeft minstens één materiaal nodig.'}), 400
        # Dedupe, preserve order, force strings.
        materials = list(dict.fromkeys(str(m).strip() for m in raw if str(m).strip()))
        if not materials:
            return jsonify({'error': 'Een groep heeft minstens één materiaal nodig.'}), 400
        gid = str(uuid.uuid4())
        group = {
            'id': gid,
            'name': name,
            'materials': materials,
            'created_at': datetime.now().isoformat(),
            'source': str(body.get('source') or ''),
        }
        sess['material_groups'][gid] = group
        save_sessions_to_disk()
        payload = groups_payload(sess, engine)
        payload.update({'success': True, 'group': group})
        return jsonify(payload)

    @bp.route('/api/material_groups/<gid>', methods=['PATCH'])
    def rename_group(gid):
        sess, engine, err = _sess_or_error()
        if err:
            return err
        group = sess['material_groups'].get(gid)
        if group is None:
            return jsonify({'error': _ERR_NOT_FOUND}), 404
        name = str((request.get_json(force=True, silent=True) or {}).get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Naam mag niet leeg zijn.'}), 400
        group['name'] = name
        save_sessions_to_disk()
        payload = groups_payload(sess, engine)
        payload.update({'success': True, 'group': group})
        return jsonify(payload)

    @bp.route('/api/material_groups/<gid>', methods=['DELETE'])
    def delete_group(gid):
        sess, engine, err = _sess_or_error()
        if err:
            return err
        if gid not in sess['material_groups']:
            return jsonify({'error': _ERR_NOT_FOUND}), 404
        # Deleting the active group deactivates the global scope first.
        if sess.get('active_material_group') == gid:
            sess['active_material_group'] = None
        del sess['material_groups'][gid]
        save_sessions_to_disk()
        payload = groups_payload(sess, engine)
        payload['success'] = True
        return jsonify(payload)

    @bp.route('/api/material_groups/<gid>/activate', methods=['POST'])
    def activate_group(gid):
        sess, engine, err = _sess_or_error()
        if err:
            return err
        group = sess['material_groups'].get(gid)
        if group is None:
            return jsonify({'error': _ERR_NOT_FOUND}), 404
        sess['active_material_group'] = gid
        save_sessions_to_disk()
        payload = groups_payload(sess, engine)
        payload.update({'success': True, 'group': group})
        return jsonify(payload)

    @bp.route('/api/material_groups/deactivate', methods=['POST'])
    def deactivate_group():
        sess, engine, err = _sess_or_error()
        if err:
            return err
        sess['active_material_group'] = None
        save_sessions_to_disk()
        payload = groups_payload(sess, engine)
        payload['success'] = True
        return jsonify(payload)

    return bp
