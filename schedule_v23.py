"""Periode kalender dan pengiriman rekap/tagihan, memakai polling bot yang sama."""
import calendar
from datetime import datetime, timedelta

from core import day_label, month_range, read_day, rupiah
from excel_export import build_excel
from ui import Reply, Document, button

REPORT_NAMES={'weekly':'Mingguan','monthly':'Bulanan'}


def report_window(kind, now):
    if kind=='weekly':
        end=now.date()-timedelta(days=now.weekday())
        return end-timedelta(days=7),end
    if kind=='monthly':
        end=now.date().replace(day=1)
        return month_range((end-timedelta(days=1)).strftime('%Y-%m'))
    raise ValueError('Jenis rekap tidak dikenal.')


def report_due(kind, at_time, now):
    hour,minute=map(int,at_time.split(':'))
    if kind=='weekly':
        due=(now-timedelta(days=now.weekday())).replace(hour=hour,minute=minute,second=0,microsecond=0)
        if due>now: due-=timedelta(days=7)
    elif kind=='monthly':
        due=now.replace(day=1,hour=hour,minute=minute,second=0,microsecond=0)
        if due>now: due=(due-timedelta(days=1)).replace(day=1)
    else: raise ValueError('Jenis rekap tidak dikenal.')
    start,end=report_window(kind,due)
    return due,start,end


def next_report_time(kind, at_time, now):
    hour,minute=map(int,at_time.split(':'))
    if kind=='weekly':
        due=(now-timedelta(days=now.weekday())).replace(hour=hour,minute=minute,second=0,microsecond=0)
        if due<=now: due+=timedelta(days=7)
    else:
        due=now.replace(day=1,hour=hour,minute=minute,second=0,microsecond=0)
        if due<=now:
            next_month=month_range(now.strftime('%Y-%m'))[1]
            due=due.replace(year=next_month.year,month=next_month.month)
    return due


def bill_due(bill, period, zone):
    start,_=month_range(period)
    day=min(bill['day_of_month'],calendar.monthrange(start.year,start.month)[1])
    hour,minute=map(int,bill['at_time'].split(':'))
    return datetime(start.year,start.month,day,hour,minute,tzinfo=zone)


def first_bill_month(values, now):
    month=now.strftime('%Y-%m')
    if bill_due(values,month,now.tzinfo)<now:
        month=month_range(month)[1].strftime('%Y-%m')
    return month


def make_summary(bot, uid, kind, start, end, with_excel=False):
    if kind not in REPORT_NAMES: raise ValueError('Jenis rekap tidak dikenal.')
    rows=bot.store.rows(uid,start,end)
    if kind=='weekly': previous_start,previous_end=start-timedelta(days=7),start
    else: previous_start,previous_end=month_range((start-timedelta(days=1)).strftime('%Y-%m'))
    previous=bot.store.rows(uid,previous_start,previous_end)
    total,old=sum(r['amount'] for r in rows),sum(r['amount'] for r in previous)
    delta=total-old
    text=[f'REKAP {REPORT_NAMES[kind].upper()}',f'{day_label(start)} – {day_label(end-timedelta(days=1))}',
          f'Total: {rupiah(total)}',f'Jumlah: {len(rows)} catatan','',
          f'Periode pembanding: {day_label(previous_start)} – {day_label(previous_end-timedelta(days=1))}',
          f'Total sebelumnya: {rupiah(old)}']
    if delta==0: text.append('Pengeluaran tetap sama.')
    else:
        change='Naik' if delta>0 else 'Turun'
        text.append(f'{change} {rupiah(abs(delta))}'+(f" ({abs(delta)*100/old:.1f}%)".replace('.',',') if old else ''))
    if not old: text.append('Persentase tidak dihitung karena total sebelumnya nol.')
    categories={}
    for row in rows: categories[row['category']]=categories.get(row['category'],0)+row['amount']
    text+=['','KATEGORI TERBESAR']
    text += [f'{i}. {name}: {rupiah(amount)}' for i,(name,amount) in
             enumerate(sorted(categories.items(),key=lambda x:(-x[1],x[0]))[:3],1)] or ['Belum ada catatan.']
    document=None
    if with_excel:
        try:
            content=build_excel(rows,start,end,f'Rekap {REPORT_NAMES[kind]}: {start} – {end-timedelta(days=1)}',bot.now(uid).tzname())
            if len(content)>49*1024*1024: raise ValueError('Lampiran terlalu besar.')
            document=Document(f'rekap-{kind}-{start}.xlsx',content,'Rekap pengeluaran '+REPORT_NAMES[kind].lower())
        except ValueError:
            text+=['','Lampiran Excel belum tersedia atau terlalu besar. Periksa template Excel dan unduh per hari melalui Laporan.']
    return Reply('\n'.join(text),[[button('📊 Laporan','reports'),button('⚙ Atur rekap','reportschedule')]],document=document)


def send_scheduled_reports(api, bot):
    from bot import APIError
    settings=bot.store.db.execute('SELECT * FROM report_settings WHERE enabled=1 ORDER BY user_id,kind').fetchall()
    for setting in settings:
        uid,kind=setting['user_id'],setting['kind']
        if uid not in bot.allowed_ids: continue
        due,start,end=report_due(kind,setting['at_time'],bot.now(uid))
        if int(due.timestamp())<setting['activated_at']: continue
        period=start.isoformat()
        job=bot.store.report_job(uid,kind,period)
        if job and job['completed']: continue
        if job is None:
            reply=make_summary(bot,uid,kind,start,end,bool(setting['with_excel']))
            job=bot.store.save_report_job(uid,kind,period,start,end,reply.to_json(),
                                         reply.document.content if reply.document else None,bot.stamp())
            with bot.store.transaction():
                bot.store.db.execute("""UPDATE report_jobs SET completed=1,reply='',excel=NULL
                    WHERE user_id=? AND kind=? AND period<? AND completed=0""",(uid,kind,period))
        reply=Reply.from_json(job['reply'])
        try:
            if not job['text_sent']:
                api.send(uid,reply.text,reply.markup)
                bot.store.mark_report(uid,kind,period,'text_sent')
            if job['excel'] is not None and not job['doc_sent']:
                document=Document(f'rekap-{kind}-{period}.xlsx',job['excel'],'Rekap pengeluaran '+REPORT_NAMES[kind].lower())
                api.send_document(uid,document,document.caption,reply.markup)
                bot.store.mark_report(uid,kind,period,'doc_sent')
            bot.store.mark_report(uid,kind,period,'completed')
        except APIError as exc:
            if exc.code not in (400,403): raise
            bot.store.set_report_setting(uid,kind,bot.stamp(),enabled=False)
            print('Rekap otomatis dinonaktifkan karena Telegram menolak kiriman; periksa akses chat dan aktifkan ulang.')


def send_bill_reminders(api, bot):
    from bot import APIError
    for bill in bot.store.db.execute('SELECT * FROM bills WHERE enabled=1 ORDER BY user_id,id').fetchall():
        uid=bill['user_id']
        if uid not in bot.allowed_ids: continue
        now=bot.now(uid); period=now.strftime('%Y-%m')
        if period<bill['start_month']: continue
        due=bill_due(bill,period,now.tzinfo)
        if now<due: continue
        cycle=bot.store.ensure_cycle(uid,bill,period,due.date())
        if cycle['reminded_at'] is not None or cycle['expense_id'] is not None: continue
        text=(f"🔔 TAGIHAN {bill['title']}\nPeriode: {period}\nJatuh tempo: {day_label(read_day(cycle['due_on']))}\n"
              f"Nominal: {rupiah(bill['amount'])}\nKategori: {bill['category']}\n\n"
              'Sudah dibayar? Tekan tombol untuk meninjau dan mencatat pengeluarannya.')
        try:
            api.send(uid,text,{'inline_keyboard':[
                [button('Sudah dibayar → Catat',f"billpay:{bill['id']}:{period}")],
                [button('Lihat tagihan',f"billview:{bill['id']}:{period}")]]})
        except APIError as exc:
            if exc.code not in (400,403): raise
            bot.store.set_bill_enabled(uid,bill['id'],False)
            continue
        bot.store.finish_bill_reminder(uid,bill['id'],period,bot.stamp())
