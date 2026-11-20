param(
    [string]$DatabricksProfile = 'rdg-local',
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
$launcher = Join-Path $PSScriptRoot 'start-local.ps1'
$powershell = Join-Path $PSHOME 'powershell.exe'

foreach ($service in 'mcp', 'chat') {
    $arguments = @(
        '-NoExit'
        '-ExecutionPolicy', 'Bypass'
        '-File', "`"$launcher`""
        '-Service', $service
        '-Profile', "`"$DatabricksProfile`""
        '-WorkspaceHost', "`"$WorkspaceHost`""
        '-WarehouseId', $WarehouseId
        '-ServingEndpoint', $ServingEndpoint
        '-McpPort', $McpPort
        '-ChatPort', $ChatPort
    )

    Start-Process -FilePath $powershell -ArgumentList $arguments
}