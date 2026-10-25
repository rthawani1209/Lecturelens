"""Who can see and change what.

A course belongs to a group. Members of that group can read and add to it;
public (openly licensed) courses can be read by anyone, signed in or not.
Every route asks these functions, and a "no" looks exactly like "not found"
so course and lecture ids can't be probed.
"""

from uuid import UUID

import psycopg


def readable_courses(
    conn: psycopg.Connection, user_id: UUID | None, course_id: UUID | None = None
) -> list[UUID]:
    rows = conn.execute(
        """
        SELECT c.id FROM courses c
         WHERE (c.public OR EXISTS (
                SELECT 1 FROM group_members m WHERE m.group_id = c.group_id AND m.user_id = %(u)s))
           AND (%(c)s::uuid IS NULL OR c.id = %(c)s)
        """,
        {"u": user_id, "c": course_id},
    ).fetchall()
    return [r["id"] for r in rows]


def course(
    conn: psycopg.Connection, user_id: UUID | None, course_id: UUID, write: bool = False
) -> dict | None:
    """The course row if the user may read it (or change it, with write=True)."""
    return conn.execute(
        """
        SELECT c.*, m.user_id IS NOT NULL AS member FROM courses c
          LEFT JOIN group_members m ON m.group_id = c.group_id AND m.user_id = %(u)s
         WHERE c.id = %(c)s AND (m.user_id IS NOT NULL OR (c.public AND NOT %(w)s))
        """,
        {"u": user_id, "c": course_id, "w": write},
    ).fetchone()


def lecture(
    conn: psycopg.Connection, user_id: UUID | None, lecture_id: UUID, write: bool = False
) -> dict | None:
    return conn.execute(
        """
        SELECT l.*, c.public FROM lectures l JOIN courses c ON c.id = l.course_id
          LEFT JOIN group_members m ON m.group_id = c.group_id AND m.user_id = %(u)s
         WHERE l.id = %(l)s AND (m.user_id IS NOT NULL OR (c.public AND NOT %(w)s))
        """,
        {"u": user_id, "l": lecture_id, "w": write},
    ).fetchone()


def writable_group(conn: psycopg.Connection, user_id: UUID, group_id: UUID | None) -> UUID | None:
    """The group a new course goes in: the one asked for if the user is in it, else personal."""
    row = conn.execute(
        """
        SELECT g.id FROM groups g JOIN group_members m ON m.group_id = g.id
         WHERE m.user_id = %(u)s AND (g.id = %(g)s OR (%(g)s::uuid IS NULL AND g.personal))
         LIMIT 1
        """,
        {"u": user_id, "g": group_id},
    ).fetchone()
    return row["id"] if row else None
