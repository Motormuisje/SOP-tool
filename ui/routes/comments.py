"""Annotation (comment) routes — Fase 2.1.

Comments are per-session annotations anchored to a planning row, machine, or
period. They are pure metadata: they never touch the engine or the numeric
cascade, so they neither trigger a recalc nor affect golden parity. They live
on the session dict under ``comments`` and are serialised with the session.

Anchor key format: ``"{scope}||{target}||{period}"`` where
  - scope   = line type (e.g. "01. Demand forecast") or "machine"
  - target  = material number or machine code
  - period  = "YYYY-MM", the sentinel "starting_stock", or "" for row/whole
Value: ``{'text': str, 'user': str, 'updated_at': iso8601}``.
"""

from datetime import datetime
from typing import Callable

from flask import Blueprint, jsonify, request


def comment_key(scope: str, target: str, period: str = '') -> str:
    return f"{scope}||{target}||{period or ''}"


def create_comments_blueprint(
    get_active: Callable[[], tuple],
    save_sessions_to_disk: Callable[[], None],
) -> Blueprint:
    bp = Blueprint('comments', __name__)

    @bp.route('/api/comments', methods=['GET'])
    def list_comments():
        sess, _ = get_active()
        if sess is None:
            return jsonify({'comments': {}})
        return jsonify({'comments': sess.get('comments', {})})

    @bp.route('/api/comments', methods=['POST'])
    def upsert_comment():
        sess, _ = get_active()
        if sess is None:
            return jsonify({'error': 'No active session'}), 400
        data = request.get_json(silent=True) or {}
        scope = str(data.get('scope', '') or '').strip()
        target = str(data.get('target', '') or '').strip()
        period = str(data.get('period', '') or '').strip()
        text = str(data.get('text', '') or '').strip()
        user = str(data.get('user', '') or '').strip() or 'onbekend'
        if not scope or not target:
            return jsonify({'error': 'scope and target are required'}), 400
        comments = sess.setdefault('comments', {})
        key = comment_key(scope, target, period)
        if not text:
            # Empty text deletes the annotation.
            comments.pop(key, None)
            save_sessions_to_disk()
            return jsonify({'success': True, 'deleted': True, 'key': key, 'comments': comments})
        entry = {
            'text': text,
            'user': user,
            'updated_at': datetime.now().isoformat(timespec='seconds'),
        }
        comments[key] = entry
        save_sessions_to_disk()
        return jsonify({'success': True, 'key': key, 'comment': entry, 'comments': comments})

    @bp.route('/api/comments/delete', methods=['POST'])
    def delete_comment():
        sess, _ = get_active()
        if sess is None:
            return jsonify({'error': 'No active session'}), 400
        data = request.get_json(silent=True) or {}
        key = data.get('key')
        if not key:
            key = comment_key(
                str(data.get('scope', '')), str(data.get('target', '')), str(data.get('period', '')))
        comments = sess.setdefault('comments', {})
        existed = comments.pop(key, None) is not None
        save_sessions_to_disk()
        return jsonify({'success': True, 'deleted': existed, 'key': key, 'comments': comments})

    return bp
