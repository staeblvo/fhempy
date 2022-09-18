import asyncio
import codecs
import functools
import time

from .. import fhem, generic, utils
from ..core.ble import BTLEConnection

DEFAULT_TIMEOUT = 1


class blue_connect(generic.FhemModule):
    def __init__(self, logger):
        super().__init__(logger)
        self._ble_lock = asyncio.Lock()
        self._conn = None
        self.water_temp = "-"
        self.water_orp = "-"
        self.water_ph = "-"
        set_conf = {
            "measure": {"help": "Send signal to start measuring"},
        }
        self.set_set_config(set_conf)
        return

    # FHEM FUNCTION
    async def Define(self, hash, args, argsh):
        await super().Define(hash, args, argsh)
        if len(args) != 4:
            return "Usage: define my_blueconnect fhempy blue_connect MAC"
        self._mac = args[3]
        self.hash["MAC"] = self._mac
        self._conn = BTLEConnection(
            self._mac,
            keep_connected=True,
        )
        self._conn.set_callback("all", self.received_notification)
        self.create_async_task(self.update_loop())

    async def Undefine(self, hash):
        if self._conn:
            self._conn.set_keep_connected(False)
        return await super().Undefine(self.hash)

    async def set_measure(self, hash, params):
        self.create_async_task(self.measure_once())

    def received_notification(self, data):
        raw_measurement = codecs.encode(data, "hex")
        raw_temp = int(raw_measurement[4:6] + raw_measurement[2:4], 16)
        self.water_temp = float(raw_temp) / 100

        raw_ph = int(raw_measurement[8:10] + raw_measurement[6:8], 16)
        self.water_ph = (float(0x0800) - float(raw_ph)) / 232 + 7

        raw_orp = int(raw_measurement[12:14] + raw_measurement[10:12], 16)
        self.water_orp = float(raw_orp) / 4

    def blocking_measure(self):
        for cnt in range(0, 5):
            try:
                # enable notifications
                self._conn.write_characteristic(0x0014, b"\x01\x00")
                # start measuring
                self._conn.write_characteristic(0x0012, b"\x01", 60)
                break
            except Exception:
                self.logger.exception("Failed to write characteristics")
                time.sleep(5)

    async def update_loop(self):
        while True:
            try:
                await self.measure_once()
            except asyncio.CancelledError:
                break
            except Exception:
                self.logger.exception("Failed to update readings")
            await asyncio.sleep(7200)

    async def measure_once(self):
        async with self._ble_lock:
            await utils.run_blocking(functools.partial(self.blocking_measure))
        await fhem.readingsBeginUpdate(self.hash)
        await fhem.readingsBulkUpdate(self.hash, "temperature", self.water_temp)
        await fhem.readingsBulkUpdate(self.hash, "ph", self.water_ph)
        await fhem.readingsBulkUpdate(self.hash, "orp", self.water_orp)
        await fhem.readingsEndUpdate(self.hash, 1)
