import os

def check_files(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if 'VideoCapture' in content:
                            print(f"FOUND VideoCapture in: {path}")
                        if 'Starting camera for authentication' in content:
                            print(f"FOUND offending log in: {path}")
                except Exception as e:
                    pass

check_files('backend')
check_files('.')
