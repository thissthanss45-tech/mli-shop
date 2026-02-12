import os

# Имя итогового файла, куда все сохранится
OUTPUT_FILE = "full_project_code.txt"

# Папки, которые ИГНОРИРУЕМ (мусор, базы данных, настройки редактора)
IGNORE_DIRS = {
    "venv", ".venv", "__pycache__", ".git", ".idea", ".vscode", 
    "__MACOSX", "build", "dist"
}

# Файлы, которые ИГНОРИРУЕМ (чтобы не дублировать сам скрипт и базу данных)
IGNORE_FILES = {
    OUTPUT_FILE, 
    "save_project.py", 
    "shop_base.db", 
    "mli_base.db",
    ".DS_Store"
}

# Расширения файлов, которые БЕРЕМ (код и настройки)
ALLOWED_EXTENSIONS = {
    ".py", ".txt", ".md", ".env", ".json", ".yml", ".yaml", "Dockerfile"
}

def save_full_project():
    root_dir = os.getcwd()
    print(f"🚀 Начинаю сборку проекта из папки: {root_dir}")
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as outfile:
        outfile.write(f"=== ПОЛНЫЙ КОД ПРОЕКТА ===\n")
        outfile.write(f"Папка: {os.path.basename(root_dir)}\n\n")

        # Проходим по всем папкам и файлам
        for root, dirs, files in os.walk(root_dir):
            # Фильтруем папки (удаляем ненужные из обхода)
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

            for file in files:
                if file in IGNORE_FILES:
                    continue
                
                # Проверяем расширение
                _, ext = os.path.splitext(file)
                # Если файл без расширения (например Dockerfile) или имеет нужное расширение
                if ext not in ALLOWED_EXTENSIONS and file != "Dockerfile":
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, root_dir)

                try:
                    with open(file_path, "r", encoding="utf-8") as infile:
                        content = infile.read()
                        
                    # Пишем красивый разделитель и имя файла
                    outfile.write(f"\n{'='*60}\n")
                    outfile.write(f"ФАЙЛ: {rel_path}\n")
                    outfile.write(f"{'='*60}\n")
                    outfile.write(content + "\n")
                    
                    print(f"✅ Добавлен: {rel_path}")
                except Exception as e:
                    print(f"❌ Ошибка чтения {rel_path}: {e}")

    print(f"\n🎉 Готово! Весь код сохранен в файл: {OUTPUT_FILE}")

if __name__ == "__main__":
    save_full_project()