"""Host-console commands only; never receive messages from Discord."""
import asyncio
import logging
import os
import sys
import uuid

log = logging.getLogger('trex.console')


class ConsoleCommands:
    def __init__(self, raids):
        self.raids = raids
        self.fd = None
        self.buffer = ''
        self.tasks = set()

    def start(self):
        if self.fd is not None:
            return
        try:
            fd = sys.stdin.fileno()
            asyncio.get_running_loop().add_reader(fd, self.read_ready)
            self.fd = fd
            log.info('Console aktif. Reset seluruh poin: wipepoint HAPUS SEMUA POIN')
        except (AttributeError, ValueError, OSError, NotImplementedError) as exc:
            log.warning('Input console tidak tersedia (%s). Fitur wipe console nonaktif.', exc)

    def read_ready(self):
        if self.fd is None:
            return
        try:
            chunk = os.read(self.fd, 4096)
            if not chunk:
                self.stop_reader()
                return
            self.buffer += chunk.decode('utf-8', errors='replace')
            while '\n' in self.buffer:
                line, self.buffer = self.buffer.split('\n', 1)
                task = asyncio.create_task(self.execute(line.strip()))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
            if len(self.buffer) > 8192:
                self.buffer = ''
                log.warning('Input console terlalu panjang; dibuang.')
        except (OSError, ValueError) as exc:
            self.stop_reader()
            log.warning('Input console berhenti: %s', exc)

    async def execute(self, line):
        if not line:
            return
        if line != 'wipepoint HAPUS SEMUA POIN':
            log.info('Perintah console: wipepoint HAPUS SEMUA POIN (reset semua poin server).')
            return
        try:
            async with self.raids.lock:
                reset = self.raids.store.wipe_points(self.raids.guild_id, 'wispbyte-console',
                                                     'console:' + uuid.uuid4().hex)
            log.warning('Reset #%s selesai pada guild %s: %s catatan poin event, %s contribution, dan %s pengurangan direset. '
                        'Timer dan daftar peserta tetap tersimpan; poin lama tidak dipulihkan saat restart.',
                        reset['id'], self.raids.guild_id, reset['event_awards'], reset['contributions'], reset['deductions'])
        except Exception:
            log.exception('Reset poin dari console gagal; periksa database dan log.')

    def stop_reader(self):
        if self.fd is not None:
            asyncio.get_running_loop().remove_reader(self.fd)
            self.fd = None

    async def close(self):
        self.stop_reader()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
