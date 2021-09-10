const router = require('express').Router();
const { query, param } = require('express-validator');
const branch = require('../middlewares/branch');

const validateParams = require('../paramValidation/validateParams');
const createErrMsg = require('../paramValidation/createErrMsg');
const graph = require('../middlewares/graph');
const returnMsg = require('../middlewares/returnMsg');

router.get('/:idBranch/graph', [
  param('idBranch')
    .exists().withMessage(createErrMsg.missingParameter('idBranch'))
    .isInt({ min: 0 })
    .withMessage(createErrMsg.invalidParameter('idBranch')),
  query('x')
    .exists().withMessage(createErrMsg.missingParameter('x'))
    .matches(/^\d+(.\d+)?$/i)
    .withMessage(createErrMsg.invalidParameter('x')),
  query('y')
    .exists().withMessage(createErrMsg.missingParameter('y'))
    .matches(/^\d+(.\d+)?$/i)
    .withMessage(createErrMsg.invalidParameter('y')),
],
validateParams,
branch.validBranch,
graph.getGraph,
returnMsg);

module.exports = router;
