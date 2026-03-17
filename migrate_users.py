import sqlite3
from app import app, db, User, Notification


def migrate(sqlite_path='database/users.db'):
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    with app.app_context():
        db.create_all()

        cur.execute('SELECT * FROM user')
        users = cur.fetchall()
        created_users = 0

        id_map = {}
        for row in users:
            existing = User.query.filter(
                (User.username == row['username']) | (User.login_key == row['login_key'])
            ).first()
            if existing:
                id_map[row['id']] = existing.id
                continue

            user = User(
                username=row['username'],
                password_hash=row['password_hash'],
                login_key=row['login_key'],
                is_admin=bool(row['is_admin']),
                notifications_enabled=bool(row['notifications_enabled']),
                created_at=row['created_at'],
                last_login=row['last_login']
            )
            db.session.add(user)
            db.session.flush()
            id_map[row['id']] = user.id
            created_users += 1

        cur.execute('SELECT * FROM notification')
        notifications = cur.fetchall()
        created_notifications = 0
        for row in notifications:
            mapped_user = id_map.get(row['user_id'])
            if not mapped_user:
                continue
            existing = Notification.query.filter_by(
                user_id=mapped_user,
                title=row['title'],
                message=row['message'],
                created_at=row['created_at']
            ).first()
            if existing:
                continue

            notif = Notification(
                user_id=mapped_user,
                title=row['title'],
                message=row['message'],
                type=row['type'],
                read=bool(row['read']),
                created_at=row['created_at']
            )
            db.session.add(notif)
            created_notifications += 1

        db.session.commit()

    conn.close()
    print(f'Migrated users: {created_users}')
    print(f'Migrated notifications: {created_notifications}')


if __name__ == '__main__':
    migrate()
