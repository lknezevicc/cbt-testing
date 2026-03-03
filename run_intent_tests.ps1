$ErrorActionPreference = 'Stop'

Set-Location -Path $PSScriptRoot

function Get-PythonCommand {
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        return @($venvPython)
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        return @('py', '-3')
    }

    return @('python')
}

$pythonCmd = Get-PythonCommand
Write-Host "Using Python command: $($pythonCmd -join ' ')"

$pythonExe = $pythonCmd[0]
$pythonPrefixArgs = @()
if ($pythonCmd.Length -gt 1) {
    $pythonPrefixArgs = $pythonCmd[1..($pythonCmd.Length - 1)]
}

$baseArgs = @(
    '-m', 'chatbot_utils.test_intent_recognition',
    '--dialogs-dir', 'dialogs',
    '--tests-dir', 'dialogs/test',
    '--summary-output', 'intent_test_summary.json',
    '--jira-output', 'intent_test_jira_issues.json',
    '--pdf-output', 'intent_test_report.pdf'
)

$allArgs = $baseArgs + $args

& $pythonExe @pythonPrefixArgs @allArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host 'Intent tests failed.'
    exit $LASTEXITCODE
}

Write-Host ''
Write-Host 'Intent tests finished successfully.'
Write-Host '- Summary: intent_test_summary.json'
Write-Host '- Jira-like report: intent_test_jira_issues.json'
Write-Host '- PDF report: intent_test_report.pdf'
