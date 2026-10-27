"""Pulihkan database dengan pemeriksaan dan konfirmasi interaktif, tanpa token Telegram."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys

from backups import RuntimeLock, readonly, snapshot_database, restore_database

ROOT = Path(__file__).resolve().parent


def database_path(config, override=None):
    try: data = json.loads(config.read_text(encoding='utf-8-sig'))
    except FileNotFoundError: data = {}
    if not isinstance(data,dict): raise ValueError('config.json harus berupa objek JSON.')
    value = override or os.environ.get('DB_PATH') or data.get('database','data/pengeluaran.db')
    if not isinstance(value,str) or not value.strip() or value==':memory:':
        raise ValueError('Lokasi database tidak valid.')
    return (config.resolve().parent/value).resolve()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Cadangan dan pemulihan database bot pengeluaran v2.4. Hentikan bot dahulu.')
    parser.add_argument('action',choices=('restore','backup'))
    parser.add_argument('source',nargs='?',type=Path,help='File cadangan .db untuk restore')
    parser.add_argument('--config',type=Path,default=ROOT/'config.json')
    parser.add_argument('--database',help='Database tujuan, misalnya /data/pengeluaran.db')
    args = parser.parse_args(argv)
    try:
        target = database_path(args.config,args.database)
        if args.action=='backup':
            if not target.is_file(): raise ValueError('Database belum tersedia.')
            tag = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
            output = target.parent/'backups'/target.stem/f'manual-{tag}.db'
            with RuntimeLock(target),closing(readonly(target)) as db:
                snapshot_database(db,output)
            print('Cadangan lengkap tersimpan:',output)
            return 0
        source = args.source or Path(input('Lokasi file cadangan .db: ').strip().strip('"'))
        def confirm(summary):
            print('\nRingkasan file yang akan dipulihkan:')
            print(f"{summary['active']} catatan aktif; {summary['deleted']} terhapus; {summary['changes']} perubahan; {summary['users']} pengguna.")
            print(f"{summary['wallets']} dompet; {summary['incomes']} pemasukan aktif; {summary['transfers']} transfer aktif.")
            print('ID bot:',summary['bot_id'] or 'Belum terikat')
            print('Database tujuan:',target)
            print('Data tujuan akan DIGANTI, bukan digabung. Salinan data tujuan dibuat terlebih dahulu.')
            return input('Ketik PULIHKAN untuk melanjutkan, atau Enter untuk batal: ').strip()=='PULIHKAN'
        result = restore_database(source,target,confirm)
        if result is None:
            print('Dibatalkan. Database tujuan tidak berubah.')
            return 0
        print('Pemulihan berhasil:',result['target'])
        if result['previous']: print('Salinan sebelum pemulihan:',result['previous'])
        print('Jalankan bot dengan token bot yang sama, lalu buka /menu. Draf dan tombol lama perlu dibuka kembali.')
        return 0
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError) as exc:
        print('Pemulihan/cadangan tidak dilanjutkan:',exc)
        return 1
    except (EOFError,KeyboardInterrupt):
        print('\nDibatalkan.')
        return 1


if __name__=='__main__': sys.exit(main())
