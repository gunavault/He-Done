"""Guild quest lifecycle and rewards in the shared SQLite point ledger."""
from datetime import datetime, timedelta

from schedule import WIB


def quest_now(now=None):
    return (now or datetime.now(WIB)).astimezone(WIB)


class QuestStoreMixin:
    def init_quest_tables(self):
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS guild_quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id TEXT NOT NULL,
                request_id TEXT NOT NULL UNIQUE,title TEXT NOT NULL,detail TEXT NOT NULL,
                points INTEGER NOT NULL CHECK(points BETWEEN 1 AND 1000000),
                hours INTEGER NOT NULL CHECK(hours BETWEEN 1 AND 720),
                status TEXT NOT NULL DEFAULT 'available',active_attempt_id INTEGER,
                revision INTEGER NOT NULL DEFAULT 1,created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS guild_quests_status ON guild_quests(guild_id,status,id);
            CREATE TABLE IF NOT EXISTS guild_quest_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id TEXT NOT NULL,
                quest_id INTEGER NOT NULL REFERENCES guild_quests(id),user_id TEXT NOT NULL,
                status TEXT NOT NULL,started_at TEXT NOT NULL,deadline TEXT NOT NULL,
                submitted_at TEXT,proof TEXT NOT NULL DEFAULT '',review_note TEXT NOT NULL DEFAULT '',
                reviewed_by TEXT,updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS guild_quest_one_member
                ON guild_quest_attempts(guild_id,user_id) WHERE status IN ('in_progress','submitted');
            CREATE UNIQUE INDEX IF NOT EXISTS guild_quest_one_attempt
                ON guild_quest_attempts(quest_id) WHERE status IN ('in_progress','submitted');
            CREATE TABLE IF NOT EXISTS guild_quest_rewards (
                quest_id INTEGER PRIMARY KEY REFERENCES guild_quests(id),
                attempt_id INTEGER NOT NULL UNIQUE REFERENCES guild_quest_attempts(id),
                guild_id TEXT NOT NULL,user_id TEXT NOT NULL,points INTEGER NOT NULL CHECK(points>0),
                approved_by TEXT NOT NULL,awarded_at TEXT NOT NULL,voided INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS guild_quest_rewards_user ON guild_quest_rewards(guild_id,user_id,voided);
            CREATE TABLE IF NOT EXISTS guild_quest_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,quest_id INTEGER NOT NULL REFERENCES guild_quests(id),
                attempt_id INTEGER,actor_id TEXT NOT NULL,action TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guild_quest_dashboard (
                guild_id TEXT PRIMARY KEY,channel_id TEXT NOT NULL,message_id TEXT NOT NULL
            );
        ''')

    def _quest_audit(self, quest_id, actor_id, action, now, attempt_id=None, detail=''):
        self.db.execute('''INSERT INTO guild_quest_audit
            (quest_id,attempt_id,actor_id,action,detail,at) VALUES(?,?,?,?,?,?)''',
            (quest_id, attempt_id, str(actor_id), action, detail, now.isoformat()))

    def _quest_fields(self, title, detail, points, hours):
        title, detail = title.strip(), detail.strip()
        if not 1 <= len(title) <= 100 or not 1 <= len(detail) <= 1500:
            raise ValueError('Judul harus 1–100 karakter dan detail 1–1500 karakter.')
        if type(points) is not int or not 1 <= points <= 1000000:
            raise ValueError('Poin quest harus angka bulat 1–1000000.')
        if type(hours) is not int or not 1 <= hours <= 720:
            raise ValueError('Durasi harus angka bulat 1–720 jam.')
        return title, detail

    def quest_get(self, guild_id, quest_id):
        row = self.db.execute('''SELECT q.*,a.user_id,a.deadline,a.proof,a.review_note,a.submitted_at,
            a.status AS attempt_status FROM guild_quests q LEFT JOIN guild_quest_attempts a
            ON a.id=q.active_attempt_id WHERE q.guild_id=? AND q.id=?''', (str(guild_id), quest_id)).fetchone()
        if row is None:
            raise ValueError('Quest tidak ditemukan di server ini.')
        return row

    def quest_list(self, guild_id, status=None, page=0, limit=10):
        where, params = 'q.guild_id=?', [str(guild_id)]
        if status is not None:
            where += ' AND q.status=?'
            params.append(status)
        else:
            where += " AND q.status IN ('available','in_progress','submitted')"
        return self.db.execute(f'''SELECT q.*,a.user_id,a.deadline FROM guild_quests q
            LEFT JOIN guild_quest_attempts a ON a.id=q.active_attempt_id WHERE {where}
            ORDER BY q.id DESC LIMIT ? OFFSET ?''', (*params, limit, page * limit)).fetchall()

    def quest_counts(self, guild_id):
        return {row['status']: row['n'] for row in self.db.execute(
            'SELECT status,COUNT(*) AS n FROM guild_quests WHERE guild_id=? GROUP BY status', (str(guild_id),))}

    def quest_create(self, guild_id, actor_id, title, detail, points, hours, request_id, now=None):
        title, detail = self._quest_fields(title, detail, points, hours)
        now = quest_now(now)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT * FROM guild_quests WHERE request_id=?', (str(request_id),)).fetchone()
            if old:
                if (old['guild_id'], old['created_by'], old['title'], old['detail'], old['points'], old['hours']) != (str(guild_id), str(actor_id), title, detail, points, hours):
                    raise ValueError('Permintaan posting sudah dipakai untuk quest berbeda.')
                return self.quest_get(guild_id, old['id'])
            cur = self.db.execute('''INSERT INTO guild_quests
                (guild_id,request_id,title,detail,points,hours,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)''', (str(guild_id), str(request_id), title, detail, points, hours,
                                              str(actor_id), now.isoformat(), now.isoformat()))
            self._quest_audit(cur.lastrowid, actor_id, 'create', now)
            return self.quest_get(guild_id, cur.lastrowid)

    def quest_edit(self, guild_id, quest_id, actor_id, revision, title, detail, points, hours, now=None):
        title, detail = self._quest_fields(title, detail, points, hours)
        now = quest_now(now)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.quest_get(guild_id, quest_id)
            if old['status'] != 'available' or old['revision'] != revision:
                raise ValueError('Quest berubah atau sudah diambil. Buka ulang panel leader.')
            self.db.execute('''UPDATE guild_quests SET title=?,detail=?,points=?,hours=?,revision=revision+1,
                updated_at=? WHERE id=?''', (title, detail, points, hours, now.isoformat(), quest_id))
            self._quest_audit(quest_id, actor_id, 'edit', now)

    def _quest_expire(self, guild_id, now):
        rows = self.db.execute("SELECT * FROM guild_quest_attempts WHERE guild_id=? AND status='in_progress' AND deadline<=?",
                               (str(guild_id), now.isoformat())).fetchall()
        for row in rows:
            self.db.execute("UPDATE guild_quest_attempts SET status='expired',updated_at=? WHERE id=?", (now.isoformat(), row['id']))
            self.db.execute("""UPDATE guild_quests SET status='available',active_attempt_id=NULL,
                revision=revision+1,updated_at=? WHERE id=? AND active_attempt_id=?""",
                (now.isoformat(), row['quest_id'], row['id']))
            self._quest_audit(row['quest_id'], 'scheduler', 'expire', now, row['id'])
        return len(rows)

    def quest_expire(self, guild_id, now=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            return self._quest_expire(guild_id, quest_now(now))

    def quest_current(self, guild_id, user_id):
        return self.db.execute('''SELECT q.*,a.id AS attempt_id,a.status AS attempt_status,
            a.user_id,a.deadline,a.proof,a.review_note,a.submitted_at
            FROM guild_quest_attempts a JOIN guild_quests q ON q.id=a.quest_id
            WHERE a.guild_id=? AND a.user_id=? AND a.status IN ('in_progress','submitted')''',
            (str(guild_id), str(user_id))).fetchone()

    def quest_claim(self, guild_id, quest_id, user_id, now=None):
        now = quest_now(now)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self._quest_expire(guild_id, now)
            old = self.quest_current(guild_id, user_id)
            if old:
                if old['id'] == quest_id:
                    return old  # Duplicate Accept does not extend the deadline.
                raise ValueError('Kamu masih mempunyai satu quest aktif atau menunggu persetujuan.')
            quest = self.quest_get(guild_id, quest_id)
            if quest['status'] != 'available':
                raise ValueError('Quest sudah diambil/ditutup. Buka kembali Accept Quest.')
            cur = self.db.execute('''INSERT INTO guild_quest_attempts
                (guild_id,quest_id,user_id,status,started_at,deadline,updated_at) VALUES(?,?,?,'in_progress',?,?,?)''',
                (str(guild_id), quest_id, str(user_id), now.isoformat(),
                 (now + timedelta(hours=quest['hours'])).isoformat(), now.isoformat()))
            self.db.execute("""UPDATE guild_quests SET status='in_progress',active_attempt_id=?,
                revision=revision+1,updated_at=? WHERE id=?""", (cur.lastrowid, now.isoformat(), quest_id))
            self._quest_audit(quest_id, user_id, 'accept', now, cur.lastrowid)
            return self.quest_current(guild_id, user_id)

    def _quest_member_attempt(self, guild_id, quest_id, user_id, attempt_id):
        quest = self.quest_get(guild_id, quest_id)
        if (quest['active_attempt_id'] != attempt_id or quest['user_id'] != str(user_id)
                or quest['status'] not in ('in_progress', 'submitted')):
            raise ValueError('Panel quest sudah tidak aktif atau bukan milikmu. Buka Accept Quest lagi.')
        return quest

    def quest_abort(self, guild_id, quest_id, user_id, attempt_id, now=None):
        now = quest_now(now)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self._quest_member_attempt(guild_id, quest_id, user_id, attempt_id)
            self.db.execute("UPDATE guild_quest_attempts SET status='aborted',updated_at=? WHERE id=?", (now.isoformat(), attempt_id))
            self.db.execute("""UPDATE guild_quests SET status='available',active_attempt_id=NULL,
                revision=revision+1,updated_at=? WHERE id=?""", (now.isoformat(), quest_id))
            self._quest_audit(quest_id, user_id, 'abort', now, attempt_id)

    def quest_submit(self, guild_id, quest_id, user_id, attempt_id, proof='', now=None):
        now = quest_now(now)
        proof = proof.strip()
        if len(proof) > 1000:
            raise ValueError('Catatan/bukti maksimal 1000 karakter.')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            quest = self._quest_member_attempt(guild_id, quest_id, user_id, attempt_id)
            if quest['status'] == 'submitted':
                if quest['proof'] == proof:
                    return
                raise ValueError('Quest sudah disubmit; tunggu pemeriksaan leader.')
            if now >= datetime.fromisoformat(quest['deadline']):
                raise ValueError('Waktu quest sudah habis; quest akan kembali tersedia.')
            self.db.execute("""UPDATE guild_quest_attempts SET status='submitted',proof=?,submitted_at=?,
                updated_at=? WHERE id=?""", (proof, now.isoformat(), now.isoformat(), attempt_id))
            self.db.execute("UPDATE guild_quests SET status='submitted',revision=revision+1,updated_at=? WHERE id=?", (now.isoformat(), quest_id))
            self._quest_audit(quest_id, user_id, 'submit', now, attempt_id, proof)

    def quest_review(self, guild_id, quest_id, attempt_id, actor_id, approve, note='', now=None, revision=None):
        now = quest_now(now)
        note = note.strip()
        if len(note) > 1000 or (not approve and not note):
            raise ValueError('Catatan revisi wajib diisi, maksimal 1000 karakter.')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            quest = self.quest_get(guild_id, quest_id)
            if quest['status'] == 'completed' and quest['active_attempt_id'] == attempt_id and approve:
                return False  # Never recreate a wiped or previously awarded reward.
            if revision is not None and quest['revision'] != revision:
                raise ValueError('Quest berubah sejak dipilih. Pilih ulang untuk memeriksa data terbaru.')
            if quest['status'] != 'submitted' or quest['active_attempt_id'] != attempt_id:
                raise ValueError('Submission sudah berubah/diproses. Buka ulang panel leader.')
            if approve:
                self.db.execute('''INSERT INTO guild_quest_rewards
                    (quest_id,attempt_id,guild_id,user_id,points,approved_by,awarded_at) VALUES(?,?,?,?,?,?,?)''',
                    (quest_id, attempt_id, str(guild_id), quest['user_id'], quest['points'], str(actor_id), now.isoformat()))
                status, quest_status = 'approved', 'completed'
            else:
                expired = now >= datetime.fromisoformat(quest['deadline'])
                status, quest_status = ('expired', 'available') if expired else ('in_progress', 'in_progress')
            self.db.execute('''UPDATE guild_quest_attempts SET status=?,review_note=?,reviewed_by=?,updated_at=? WHERE id=?''',
                            (status, note, str(actor_id), now.isoformat(), attempt_id))
            self.db.execute('''UPDATE guild_quests SET status=?,active_attempt_id=?,revision=revision+1,updated_at=? WHERE id=?''',
                            (quest_status, None if quest_status == 'available' else attempt_id, now.isoformat(), quest_id))
            self._quest_audit(quest_id, actor_id, 'approve' if approve else 'revision', now, attempt_id, note)
            return True

    def quest_withdraw(self, guild_id, quest_id, actor_id, revision, now=None):
        now = quest_now(now)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            quest = self.quest_get(guild_id, quest_id)
            if quest['status'] != 'available' or quest['revision'] != revision:
                raise ValueError('Hanya quest tersedia yang belum berubah yang dapat ditarik.')
            self.db.execute("UPDATE guild_quests SET status='withdrawn',revision=revision+1,updated_at=? WHERE id=?", (now.isoformat(), quest_id))
            self._quest_audit(quest_id, actor_id, 'withdraw', now)

    def quest_board(self, guild_id):
        return self.db.execute('SELECT * FROM guild_quest_dashboard WHERE guild_id=?', (str(guild_id),)).fetchone()

    def quest_set_board(self, guild_id, channel_id, message_id):
        with self.db:
            self.db.execute('''INSERT INTO guild_quest_dashboard VALUES(?,?,?) ON CONFLICT(guild_id)
                DO UPDATE SET channel_id=excluded.channel_id,message_id=excluded.message_id''',
                (str(guild_id), str(channel_id), str(message_id)))
