import openpyxl

def parse_estimate_file(file_path):
    """
    Читает Excel файл и возвращает список работ.
    Ожидаемый формат:
    A: Название работы | B: Ед. изм. | C: Кол-во | D: Цена
    """
    workbook = openpyxl.load_workbook(file_path)
    sheet = workbook.active
    
    tasks = []
    
    # Пропускаем первую строку (шапку) и идем до конца
    for row in sheet.iter_rows(min_row=2, values_only=True):
        # row - это кортеж (A, B, C, D...)
        work_name = row[0]
        unit = row[1]
        quantity = row[2]
        price = row[3]

        # Если строка пустая - пропускаем
        if not work_name:
            continue

        # Чистим данные от мусора
        try:
            qty_clean = float(str(quantity).replace(',', '.')) if quantity else 0
            price_clean = float(str(price).replace(',', '.')) if price else 0
            
            tasks.append({
                'work_name': str(work_name),
                'unit': str(unit),
                'total_quantity': qty_clean,
                'price_per_unit': price_clean
            })
        except ValueError:
            print(f"⚠️ Ошибка чтения строки: {work_name}")
            continue
            
    return tasks