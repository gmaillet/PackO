const fs = require('fs');
const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');

const swaggerUi = require('swagger-ui-express');
const YAML = require('yamljs');
const debug = require('debug');

const { argv } = require('yargs');

const app = express();

global.dir_cache = argv.cache ? argv.cache : 'cache';
debug.log(`using cache directory: ${global.dir_cache}`);

const wmts = require('./routes/wmts');
const graph = require('./routes/graph');
const patchs = require('./routes/patchs');

app.cache_mtd = JSON.parse(fs.readFileSync(`${global.dir_cache}/cache_mtd.json`));
// app.cacheRoot = argv.cache ? argv.cache : 'cache';
const PORT = argv.port ? argv.port : 8081;

// on charge les mtd du cache
app.cache_mtd = JSON.parse(fs.readFileSync(`${global.dir_cache}/cache_mtd.json`));
app.tileSet = JSON.parse(fs.readFileSync(`${global.dir_cache}/tileSet.json`));
app.activePatchs = JSON.parse(fs.readFileSync(`${global.dir_cache}/activePatchs.geojson`));
app.unactivePatchs = JSON.parse(fs.readFileSync(`${global.dir_cache}/unactivePatchs.geojson`));

// on trouve l'Id du prochain patch (max des Id + 1)
app.currentPatchId = 0;
app.activePatchs.features.forEach((feature) => {
  if (feature.patchId >= app.currentPatchId) {
    app.currentPatchId = feature.patchId + 1;
  }
});
app.unactivePatchs.features.forEach((feature) => {
  if (feature.patchId >= app.currentPatchId) {
    app.currentPatchId = feature.patchId + 1;
  }
});

app.use(cors());
app.use(bodyParser.json());

app.use((req, res, next) => {
  // debug.log(req.method, ' ', req.path, ' ', req.body);
  // debug.log(`received at ${Date.now()}`);
  next();
});

const options = {
  customCss: '.swagger-ui .topbar { display: none }',
};

const swaggerDocument = YAML.load('./doc/swagger.yml');

app.use('/doc', swaggerUi.serve, swaggerUi.setup(swaggerDocument, options));

app.use('/', wmts);
app.use('/', graph);
app.use('/', patchs);

module.exports = app.listen(PORT, () => {
  debug.log(`URL de l'api : http://localhost:${PORT} \nURL de la documentation swagger : http://localhost:${PORT}/doc`);
});
