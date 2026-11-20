param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('mcp', 'chat')]
    [string]$Service,
    [string]$Profile = 'rdg-local',
    [string]$WorkspaceHost = $env:DATABRICKS_HOST,
    [string]$WarehouseId = $env:DATABRICKS_WAREHOUSE_ID,
    [string]$ServingEndpoint = 'databricks-claude-sonnet-5',
    [ValidateRange(1, 65535)]
    [int]$McpPort = 8000,
    [ValidateRange(1, 65535)]
    [int]$ChatPort = 8501
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($WorkspaceHost) -or [string]::IsNullOrWhiteSpace($WarehouseId)) {
    throw 'Set DATABRICKS_HOST and DATABRICKS_WAREHOUSE_ID, or pass -WorkspaceHost and -WarehouseId. See README.md.'
}
$repoRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw 'Create the project .venv and install both app requirements first. See README.md.'
}

$cliFolder = Join-Path $env:USERPROFILE 'databricks-cli'
if (Test-Path (Join-Path $cliFolder 'databricks.exe')) {
    $env:PATH = "$cliFolder;$env:PATH"
}
if (-not (Get-Command databricks -ErrorAction SilentlyContinue)) {
    throw 'Databricks CLI is not on PATH or in your user databricks-cli folder.'
}

$env:DATABRICKS_HOST = $WorkspaceHost
$env:DATABRICKS_CONFIG_PROFILE = $Profile
$env:DATABRICKS_AUTH_TYPE = 'databricks-cli'
$env:DATABRICKS_WAREHOUSE_ID = $WarehouseId
$env:SERVING_ENDPOINT = $ServingEndpoint
$env:MCP_SERVER_URL = "http://127.0.0.1:$McpPort/mcp"
$env:MCP_HOST = '127.0.0.1'
$env:DATABRICKS_APP_PORT = "$McpPort"

if ($Service -eq 'mcp') {
    & $python (Join-Path $repoRoot 'mcp_server\app.py')
} else {
    & $python -m streamlit run (Join-Path $repoRoot 'chat_app\app.py') --server.address 127.0.0.1 --server.port $ChatPort --server.headless true --browser.gatherUsageStats false
}
exit $LASTEXITCODE