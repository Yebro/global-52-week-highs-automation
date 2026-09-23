$ErrorActionPreference = 'Stop'
$trackerRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $trackerRoot '.venv\Scripts\python.exe'
$visualization = 'C:\Users\USER\.codex\visualizations\2026\08\13\019ff9e6-dc6f-7030-8bb3-8f37c6c805b9\global-52-week-highs-20260902.html'

& $python (Join-Path $trackerRoot 'collect.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python (Join-Path $trackerRoot 'build_dashboard.py') --visualization-output $visualization
exit $LASTEXITCODE
