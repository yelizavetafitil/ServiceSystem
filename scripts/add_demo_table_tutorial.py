"""Add or update demo CMS article with HTML table (rowspan). Run: python scripts/add_demo_table_tutorial.py"""
from wsgi import app
from servicesystem.extensions import db
from servicesystem.models import Contract, ContractContentAccess, Tutorial

DEMO_SLUG = "demo-zulu-limits-table"

CONTENT = """# Ограничения демо-версий (пробный материал)

Пример таблицы с объединёнными ячейками для проверки предпросмотра и публикации.

<table>
<thead>
<tr>
<th>Продукт</th>
<th>Задача</th>
<th>Ограничение</th>
</tr>
</thead>
<tbody>
<tr>
<td rowspan="3">ZuluGIS и ZuluXTools</td>
<td>Редактирование векторных слоёв</td>
<td rowspan="2">В каждый слой можно ввести не более 150 объектов</td>
</tr>
<tr>
<td>Трансформация растров</td>
</tr>
<tr>
<td>Запись в растр</td>
<td>На растре будут отображены надписи Zulu Demo Version</td>
</tr>
<tr>
<td rowspan="3">ZuluServer</td>
<td>Число соединений</td>
<td>Количество одновременных подключений не более одного</td>
</tr>
<tr>
<td>Редактирование</td>
<td>Те же ограничения, что и для ZuluGIS</td>
</tr>
<tr>
<td>Веб-службы ZuluServer (WMS/WFS/ZWS)</td>
<td>250 запросов в сутки</td>
</tr>
<tr>
<td rowspan="2">ZuluThermo</td>
<td>Наладочный расчёт</td>
<td rowspan="2">Суммарное количество потребителей и обобщённых потребителей в рассчитываемой подсети не должно превышать 15</td>
</tr>
<tr>
<td>Поверочный расчёт</td>
</tr>
</tbody>
</table>
"""


def main():
    with app.app_context():
        t = Tutorial.query.filter_by(slug=DEMO_SLUG).first()
        if not t:
            t = Tutorial(
                title="Демо: таблица ограничений Zulu",
                slug=DEMO_SLUG,
                category="Примеры оформления",
                tags="демо, таблица, zulu, cms",
                content_md=CONTENT,
                is_published=True,
            )
            db.session.add(t)
            db.session.flush()
            print(f"Created tutorial id={t.id} slug={DEMO_SLUG}")
        else:
            t.title = "Демо: таблица ограничений Zulu"
            t.content_md = CONTENT
            t.is_published = True
            print(f"Updated tutorial id={t.id} slug={DEMO_SLUG}")

        for c in Contract.query.filter(Contract.status.in_(["active_warranty", "active_post_warranty"])).all():
            exists = ContractContentAccess.query.filter_by(
                contract_id=c.id, content_type="tutorial", content_id=t.id
            ).first()
            if not exists:
                db.session.add(
                    ContractContentAccess(contract_id=c.id, content_type="tutorial", content_id=t.id)
                )
        db.session.commit()
        print("Done. Open: /cabinet/tutorials/" + DEMO_SLUG)
        print("Edit:   /admin/tutorials/" + str(t.id) + "/edit")


if __name__ == "__main__":
    main()
