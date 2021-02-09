(function () {
  "use strict";

  angular.module("web").service("DataService", DataService);
  function DataService($log, api, jsonapi_parser) {
    var self = this;

    self.getParametersSchema = function (endpoint) {
      return api.apiCall("schemas/" + endpoint, "GET");
    };

    // SCHEMAS
    self.getStudySchema = function () {
      return self.getParametersSchema("study");
    };
    self.getDatasetSchema = function (study) {
      return self.getParametersSchema("study/" + study + "/datasets");
    };
    self.getSampleSchema = function (study) {
      var data = { get_schema: true };
      return api.apiCall("study/" + study + "/samples", "POST", data);
    };
    self.getPhenotypeSchema = function (study) {
      return self.getParametersSchema("study/" + study + "/phenotypes");
    };
    self.getTechnicalMetadataSchema = function (study) {
      return self.getParametersSchema("study/" + study + "/technicals");
    };
    self.getGroupSchema = function (study) {
      var data = { get_schema: true };
      return api.apiCall("admin/groups", "POST", data);
    };
    self.getInstituteSchema = function (study) {
      return self.getParametersSchema("admin/institutes");
    };

    // STUDIES
    self.getStudies = function () {
      return jsonapi_parser.parseResponse(api.apiCall("study", "GET"));
    };
    self.saveStudy = function (data) {
      return api.postFormData("study", "POST", data);
    };
    self.getStudyInfo = function (study) {
      return jsonapi_parser.parseResponse(api.apiCall("study/" + study, "GET"));
    };
    self.deleteStudy = function (study) {
      return api.apiCall("study/" + study, "DELETE");
    };
    self.updateStudy = function (study, data) {
      return api.apiCall("study/" + study, "PUT", data);
    };

    // DATASETS
    self.getDatasets = function (study) {
      return jsonapi_parser.parseResponse(
        api.apiCall("study/" + study + "/datasets", "GET")
      );
    };
    self.saveDataset = function (study, data) {
      return api.apiCall("study/" + study + "/datasets", "POST", data);
    };
    self.getDatasetInfo = function (dataset) {
      return jsonapi_parser.parseResponse(
        api.apiCall("dataset/" + dataset, "GET")
      );
    };
    self.getDatasetAccess = function (dataset) {
      return jsonapi_parser.parseResponse(
        api.apiCall("dataset/" + dataset + "/access", "GET")
      );
    };
    self.shareDataset = function (dataset, email) {
      var data = { user: email };
      return api.apiCall("dataset/" + dataset + "/access", "POST", data);
    };
    self.updateDataset = function (dataset, data) {
      return api.apiCall("dataset/" + dataset, "PUT", data);
    };
    self.deleteDataset = function (dataset) {
      return api.apiCall("dataset/" + dataset, "DELETE");
    };
    self.assignMeta2Dataset = function (dataset, sample, phenotype, techmeta) {
      var data = { sample: sample, phenotype: phenotype, technical: techmeta };
      return api.apiCall("dataset/" + dataset, "PUT", data);
    };

    // SAMPLES
    self.getSamples = function (study) {
      return jsonapi_parser.parseResponse(
        api.apiCall("study/" + study + "/samples", "GET")
      );
    };
    self.saveSample = function (study, data) {
      return api.apiCall("study/" + study + "/samples", "POST", data);
    };

    self.updateSample = function (sample, data) {
      return api.apiCall("sample/" + sample, "PUT", data);
    };
    self.deleteSample = function (sample) {
      return api.apiCall("sample/" + sample, "DELETE");
    };

    // PHENOTYPES
    self.getPhenotypes = function (study) {
      return jsonapi_parser.parseResponse(
        api.apiCall("study/" + study + "/phenotypes", "GET")
      );
    };
    self.savePhenotype = function (study, data) {
      return api.apiCall("study/" + study + "/phenotypes", "POST", data);
    };

    self.updatePhenotype = function (phenotype, data) {
      return api.apiCall("phenotype/" + phenotype, "PUT", data);
    };
    self.deletePhenotype = function (phenotype) {
      return api.apiCall("phenotype/" + phenotype, "DELETE");
    };

    // TECHNICAL METADATA
    self.getTechnicalMetadata = function (study) {
      return jsonapi_parser.parseResponse(
        api.apiCall("study/" + study + "/technicals", "GET")
      );
    };
    self.saveTechnicalMetadata = function (study, data) {
      return api.apiCall("study/" + study + "/technicals", "POST", data);
    };

    self.updateTechnicalMetadata = function (sample, data) {
      return api.apiCall("technical/" + sample, "PUT", data);
    };
    self.deleteTechnicalMetadata = function (sample) {
      return api.apiCall("technical/" + sample, "DELETE");
    };

    // RESOURCES
    self.getResources = function (study) {
      return jsonapi_parser.parseResponse(
        api.apiCall("study/" + study + "/resources", "GET")
      );
    };
    self.moveResource = function (resource, study) {
      return api.apiCall("study/" + study + "/resources", "POST", {
        resource: resource,
      });
    };
    self.deleteResource = function (resource) {
      return api.apiCall("resource/" + resource, "DELETE");
    };

    //FILES/STAGE

    self.getFiles = function (dataset) {
      return jsonapi_parser.parseResponse(
        api.apiCall("dataset/" + dataset + "/files", "GET")
      );
    };
    self.moveStage = function (file, dataset) {
      return api.apiCall("dataset/" + dataset + "/files", "POST", {
        file: file,
      });
    };
    self.getFileInfo = function (file) {
      return jsonapi_parser.parseResponse(api.apiCall("file/" + file, "GET"));
    };
    self.getStage = function () {
      return api.apiCall("stage");
    };

    //BATCH
    self.getBatchOperations = function (study) {
      return jsonapi_parser.parseResponse(api.apiCall("batch/" + study, "GET"));
    };
    self.importStudy = function (collection) {
      var data = { path: collection };
      return api.apiCall("batch", "POST", data);
    };
    self.importDataset = function (collection, study) {
      var data = { path: collection };
      return api.apiCall("batch/" + study, "POST", data);
    };
    self.reimport = function (accession) {
      return api.apiCall("batch/" + accession, "PUT");
    };

    // ORGANISMS
    self.getOrganisms = function () {
      return jsonapi_parser.parseResponse(api.apiCall("orgs", "GET"));
    };

    // RELATIONSHIPS
    self.saveRelationship = function (accession1, accession2, relation) {
      var data = { type: relation };
      var endpoint = "phenotype/" + accession1 + "/relationships/" + accession2;
      return api.apiCall(endpoint, "POST", data);
    };
    self.deleteRelationship = function (accession1, accession2, relation) {
      var data = { type: relation };
      var endpoint = "phenotype/" + accession1 + "/relationships/" + accession2;
      return api.apiCall(endpoint, "DELETE", data);
    };
    // AUTOCOMPLETE
    self.getPlaceOfBirth = function (query) {
      var endpoint = "city/" + query;
      return api.apiCall(endpoint, "GET");
    };
    self.getHPO = function (query) {
      var endpoint = "hpo/" + query;
      return api.apiCall(endpoint, "GET");
    };
    self.getMainEffect = function (query) {
      var endpoint = "maineffect/" + query;
      return api.apiCall(endpoint, "GET");
    };
    self.getEnrichmentKit = function (query) {
      var endpoint = "erichmentkit/" + query;
      return api.apiCall(endpoint, "GET");
    };
    self.getUserGroups = function (query) {
      var endpoint = "group/" + query;
      return api.apiCall(endpoint, "GET");
    };
    self.getUserRoles = function (query) {
      var endpoint = "role/" + query;
      return api.apiCall(endpoint, "GET");
    };

    // GROUPS
    self.getGroups = function () {
      var endpoint = "admin/groups";
      return jsonapi_parser.parseResponse(api.apiCall(endpoint, "GET"));
    };
    self.saveGroup = function (data) {
      return api.apiCall("admin/groups", "POST", data);
    };
    self.deleteGroup = function (group) {
      return api.apiCall("admin/groups/" + group, "DELETE");
    };
    self.updateGroup = function (group, data) {
      return api.apiCall("admin/groups/" + group, "PUT", data);
    };

    // INSTITUTES
    self.getInstitutes = function () {
      var endpoint = "admin/institutes";
      return jsonapi_parser.parseResponse(api.apiCall(endpoint, "GET"));
    };
    self.saveInstitute = function (data) {
      return api.apiCall("admin/institutes", "POST", data);
    };
    self.deleteInstitute = function (institute) {
      return api.apiCall("admin/institutes/" + institute, "DELETE");
    };
    self.updateInstitute = function (institute, data) {
      return api.apiCall("admin/institutes/" + institute, "PUT", data);
    };

    // SEARCH
    self.getSearchSchema = function (data) {
      return api.apiCall("search", "GET");
    };
    self.search = function (data) {
      return jsonapi_parser.parseResponse(api.apiCall("search", "POST", data));
    };

    // STATS
    self.getStats = function (is_logged) {
      if (is_logged) return api.apiCall("stats/private", "GET");
      return api.apiCall("stats/public", "GET");
    };
  }
})();
