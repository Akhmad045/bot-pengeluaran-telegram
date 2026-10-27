"""Ekspor saldo dan buku kas dengan template yang sama untuk setiap pengguna."""
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from excel_export import tag, put, update, clone_row, excel_date

TEMPLATE=Path(__file__).resolve().parent/'assets'/'arus-kas-template.xlsx'


def build_cash_excel(store, uid, start, end, zone_name):
    wallets=store.wallets(uid); names={w['id']:w['name'] for w in wallets}
    expenses=store.rows(uid,start,end); entries=store.money_rows(uid,start=start,end=end)
    if len(expenses)+len(entries)>1048500: raise ValueError('Transaksi terlalu banyak untuk satu berkas Excel.')
    try:
        with ZipFile(TEMPLATE) as source: parts={name:source.read(name) for name in source.namelist()}
    except (OSError,ValueError): raise ValueError('Template arus kas tidak ditemukan. Salin folder assets dari paket terbaru.') from None
    summary=ET.fromstring(parts['xl/worksheets/sheet1.xml']); detail=ET.fromstring(parts['xl/worksheets/sheet2.xml'])
    period=f'{start:%d/%m/%Y} – {end-timedelta(days=1):%d/%m/%Y}'
    update(summary,'A3',period); update(summary,'D3','Zona waktu: '+zone_name); update(detail,'A4',period)
    configured=all(w['opening_balance'] is not None for w in wallets)
    update(summary,'D5','Saldo berdasarkan catatan bot.' if configured else 'Saldo sementara: ada saldo awal dompet yang belum diatur.')
    items=[]
    for r in expenses:
        items.append((r['spent_on'],'E'+str(r['id']),dict(A='E'+str(r['id']),B=excel_date(date.fromisoformat(r['spent_on'])),
            C='Pengeluaran',D=names[r['wallet_id']],E='',F=r['note'],G=r['category'],H=r['amount'])))
    for r in entries:
        income=r['kind']=='income'
        items.append((r['occurred_on'],'K'+str(r['id']),dict(A='K'+str(r['id']),B=excel_date(date.fromisoformat(r['occurred_on'])),
            C='Pemasukan' if income else 'Transfer',D='' if income else names[r['wallet_id']],
            E=names[r['wallet_id'] if income else r['to_wallet_id']],F=r['note'],G=r['category'],H=r['amount'])))
    items.sort(key=lambda r:(r[0],r[1]))
    data=detail.find(tag('sheetData')); proto=data.find(f"{tag('row')}[@r='8']")
    for row in list(data):
        if int(row.get('r'))>=8: data.remove(row)
    for index,(_,_,values) in enumerate(items,8):
        row=clone_row(proto,index,values)
        row.set('ht',str(max(26,16*((len(values['F'])+39)//40),16*((max(len(values['D']),len(values['E']),len(values['G']))+22)//23))))
        row.set('customHeight','1'); data.append(row)
    if not items: data.append(clone_row(proto,8,{}))
    last=max(8,7+len(items))
    detail.insert(list(detail).index(data)+1,ET.Element(tag('autoFilter'),{'ref':f'A7:H{last}'}))
    data=summary.find(tag('sheetData')); proto=data.find(f"{tag('row')}[@r='13']")
    for row in list(data):
        if int(row.get('r'))>=13: data.remove(row)
    totals=dict(beginning=0,income=0,expense=0,balance=0)
    for index,wallet in enumerate(wallets,13):
        before=store.wallet_totals(uid,wallet['id'],start); after=store.wallet_totals(uid,wallet['id'],end)
        values=dict(A=wallet['name'],B=before['balance'],C=after['income']-before['income'],
            D=after['expense']-before['expense'],E=after['transfer_in']-before['transfer_in'],
            F=after['transfer_out']-before['transfer_out'],G=after['balance'],H='Sudah diatur' if after['configured'] else 'Belum diatur')
        criterion=f'SUBSTITUTE(SUBSTITUTE(SUBSTITUTE(A{index},"~","~~"),"*","~*"),"?","~?")'
        def total(kind, wallet_column):
            return f'SUMIFS(\'Buku kas\'!$H$8:$H${last},\'Buku kas\'!$C$8:$C${last},"{kind}",\'Buku kas\'!${wallet_column}$8:${wallet_column}${last},"="&{criterion})'
        formulas=dict(C=total('Pemasukan','E'),D=total('Pengeluaran','D'),E=total('Transfer','E'),F=total('Transfer','D'),
                      G=f'B{index}+C{index}-D{index}+E{index}-F{index}')
        row=clone_row(proto,index,values,formulas); row.set('ht','34'); row.set('customHeight','1'); data.append(row)
        for key,col in [('beginning','B'),('income','C'),('expense','D'),('balance','G')]: totals[key]+=values[col]
    wallet_last=12+len(wallets)
    for address,key,col in [('B5','beginning','B'),('B6','income','C'),('B7','expense','D'),('B8','balance','G')]:
        update(summary,address,totals[key],f'SUM({col}13:{col}{wallet_last})')
    for root,last_row,last_col in ((summary,wallet_last,'H'),(detail,last,'H')):
        dim=root.find(tag('dimension'))
        if dim is not None: dim.set('ref',f'A1:{last_col}{last_row}')
    workbook=ET.fromstring(parts['xl/workbook.xml']); props=workbook.find(tag('calcPr'))
    if props is None: props=ET.SubElement(workbook,tag('calcPr'))
    props.attrib.update(calcMode='auto',fullCalcOnLoad='1',forceFullCalc='1')
    for name,root in [('xl/worksheets/sheet1.xml',summary),('xl/worksheets/sheet2.xml',detail),('xl/workbook.xml',workbook)]:
        parts[name]=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as target:
        for name,content in parts.items(): target.writestr(name,content)
    return output.getvalue()
