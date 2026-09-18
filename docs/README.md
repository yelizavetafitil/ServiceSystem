# Инструкции по системе «Сервис ЭМСТПН»

| Документ | Для кого |
|----------|----------|
| [Инструкция пользователя (заказчик)](INSTRUKCIYA_POLZOVATELA.md) | Сотрудники облэнерго: ЛК, плагины, база знаний, заявки |
| [Инструкция администратора и аудитора](INSTRUKCIYA_ADMINISTRATORA.md) | Админ, ГИП, исполнитель: договоры, CMS, очередь, SLA |

Скриншоты: папка [`screenshots/`](screenshots/).

**Файлы Word (DOCX):**

- [INSTRUKCIYA_POLZOVATELA.docx](INSTRUKCIYA_POLZOVATELA.docx)
- [INSTRUKCIYA_ADMINISTRATORA.docx](INSTRUKCIYA_ADMINISTRATORA.docx)

Сборка DOCX из Markdown:

```bash
pip install pypandoc_binary
python scripts/build_docs_docx.py
```

Переснять скриншоты после изменений интерфейса:

```bash
docker compose up -d
python scripts/capture_docs_screenshots.py
```
