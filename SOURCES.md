# Official integration sources

Reviewed on 2026-10-24. These sources establish API availability, not an account,
an installed plugin, file entitlement or completed native acceptance.

The later [publication and route assessment](docs/PUBLICATION_AND_ROUTES.md)
also applies; API availability does not establish distribution permission.

- [Figma Plugin API](https://developers.figma.com/docs/plugins/): native document
  inspection and scene operations run inside the plugin host.
- [Plugin manifest](https://developers.figma.com/docs/plugins/manifest/):
  Figma-assigned ID, dynamic-page access and exact development network domains.
- [Plugin UI](https://developers.figma.com/docs/plugins/creating-ui/): browser UI
  messages cross the official main/UI boundary.
- [Network requests](https://developers.figma.com/docs/plugins/making-network-requests/):
  iframe Origin is null and manifest/CORS restrictions remain effective.
- [Figma API](https://developers.figma.com/docs/plugins/api/figma/): asynchronous
  node lookup and the restricted availability of `fileKey`.
- [Plugin data](https://developers.figma.com/docs/plugins/api/properties/nodes-setplugindata/):
  document data is scoped to the actual plugin ID.
- [Node export](https://developers.figma.com/docs/plugins/api/properties/nodes-exportasync/):
  native image/vector bytes.
- [Version history](https://developers.figma.com/docs/plugins/api/properties/figma-saveversionhistoryasync/):
  a newly saved version need not include every immediately preceding change.
- [REST file endpoints](https://developers.figma.com/docs/rest-api/file-endpoints/):
  file/node/image reads are not a generic canvas-node write API.
- [Official remote MCP writing](https://developers.figma.com/docs/figma-mcp-server/write-to-canvas/):
  a separate authorized route, not required by this plugin adapter.
- [Core SDK](https://github.com/dcc-mcp/dcc-mcp-core) and its
  [MIT license](https://github.com/dcc-mcp/dcc-mcp-core/blob/main/LICENSE).
- [Official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
  and its [MIT license](https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE).

No third-party plugin implementation or private source is copied into this
repository. The adapter is MIT; its runtime imports the existing official Core
SDK. Tests use Node's built-in test runner and the optional official MCP client.

## Publication and official-client boundaries

- [Plugin and widget review guidelines](https://help.figma.com/hc/en-us/articles/360039958914-Plugin-and-widget-review-guidelines)
- [Developer Terms](https://www.figma.com/legal/developer-terms/)
- [Official remote MCP setup and supported-client boundary](https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/)
- [Official MCP access and rate limits](https://developers.figma.com/docs/figma-mcp-server/rate-limits-access/)
