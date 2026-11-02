import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from console_commands import ConsoleCommands
from raid_store import RaidStore
from schedule import WIB
from datetime import datetime


class ConsoleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RaidStore(Path(self.tmp.name) / 'db.sqlite3')
        self.store.add_contribution(123, 1, 5, 'Material', 99, 'initial')
        self.console = ConsoleCommands(SimpleNamespace(store=self.store, guild_id=123, lock=asyncio.Lock()))

    async def asyncTearDown(self):
        await self.console.close()
        self.store.close()
        self.tmp.cleanup()

    async def test_confirmation_required_and_no_discord_command(self):
        for line in ('', 'wipepoint', '/wipepoint', 'wipepoint hapus semua poin'):
            await self.console.execute(line)
        self.assertEqual(self.store.point_summary(123, 1)['points'], 5)
        await self.console.execute('wipepoint HAPUS SEMUA POIN')
        self.assertEqual(self.store.point_summary(123, 1)['points'], 0)
        row = self.store.db.execute('SELECT * FROM raid_point_resets').fetchone()
        self.assertEqual(row['actor_id'], 'wispbyte-console')

    async def test_real_stdin_pipe_split_command_and_eof(self):
        read_fd, write_fd = os.pipe()
        reader = os.fdopen(read_fd)
        try:
            with patch('console_commands.sys.stdin', reader):
                self.console.start()
            os.write(write_fd, b'wipepoint HAPUS ')
            await asyncio.sleep(0.01)
            self.assertEqual(self.store.point_summary(123, 1)['points'], 5)
            os.write(write_fd, b'SEMUA POIN\n')
            for _ in range(50):
                await asyncio.sleep(0.01)
                if self.store.point_summary(123, 1)['points'] == 0:
                    break
            self.assertEqual(self.store.point_summary(123, 1)['points'], 0)
            os.close(write_fd)
            write_fd = None
            await asyncio.sleep(0.01)
            self.assertIsNone(self.console.fd)
        finally:
            await self.console.close()
            reader.close()
            if write_fd is not None:
                os.close(write_fd)
