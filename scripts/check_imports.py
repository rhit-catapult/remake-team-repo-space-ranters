modules = {
    'project.py': ['pygame', 'sys', 'random', 'time'],
    'RTS_Code_Folder/RTSmap.py': [],
    'RTS_Code_Folder/RTSsystems.py': [],
    'RTS_Code_Folder/RTSunits.py': [],
    'RTS_Code_Folder/SpaceCommander.py': [],
}

results = {}
for fname, mods in modules.items():
    results[fname] = {}
    for m in mods:
        try:
            __import__(m)
            results[fname][m] = 'ok'
        except Exception as e:
            results[fname][m] = f'error: {type(e).__name__}: {e}'

for f, r in results.items():
    print(f)
    if not r:
        print('  (no imports)')
    for mod, status in r.items():
        print(f'  {mod}: {status}')
