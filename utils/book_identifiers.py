"""Persist non-ISBN identifiers without mixing them into books.isbn."""
def save_book_uci(cursor, book_id, value, placeholder='?', only_if_empty=False):
    value = str(value or '').strip()
    if not value or value.lower() in ('none', 'null', 'n/a', '-', '—'):
        return False
    # Keep this write subject to the book's metadata lock/deletion state.
    cursor.execute(f'SELECT id FROM books WHERE id={placeholder} AND COALESCE(metadata_locked,0)=0 AND COALESCE(is_deleted,0)=0', (book_id,))
    if not cursor.fetchone():
        return False
    if only_if_empty:
        # Check the stored value in the write itself so a concurrent edit wins.
        suffix = ("ON DUPLICATE KEY UPDATE value=IF(TRIM(COALESCE(value,''))='',VALUES(value),value)"
                  if placeholder == '%s' else
                  "ON CONFLICT(`key`) DO UPDATE SET value=excluded.value "
                  "WHERE TRIM(COALESCE(settings.value,''))=''")
        cursor.execute(f'INSERT INTO settings (`key`,value) VALUES ({placeholder},{placeholder}) {suffix}',
                       (f'book:uci:{int(book_id)}', value))
    else:
        cursor.execute(f'REPLACE INTO settings (`key`,value) VALUES ({placeholder},{placeholder})',
                       (f'book:uci:{int(book_id)}', value))
    return cursor.rowcount > 0
