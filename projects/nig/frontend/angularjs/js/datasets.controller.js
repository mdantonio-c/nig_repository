(function () {
  "use strict";

  angular.module("web").controller("DatasetsController", DatasetsController);
  angular
    .module("web")
    .controller("DatasetDialogController", DatasetDialogController);
  angular
    .module("web")
    .controller("PhenotypeDialogController", PhenotypeDialogController);
  angular
    .module("web")
    .controller(
      "AutocompletePhenotypeController",
      AutocompletePhenotypeController
    );
  angular
    .module("web")
    .controller("SampleDialogController", SampleDialogController);
  angular
    .module("web")
    .controller("TechnicalDialogController", TechnicalDialogController);
  angular
    .module("web")
    .controller(
      "AutocompleteTechnicalController",
      AutocompleteTechnicalController
    );
  angular.module("web").controller("ShareDataset", ShareDataset);

  function DatasetsController(
    $scope,
    $log,
    $q,
    $state,
    $stateParams,
    $auth,
    DataService,
    FormDialogService,
    hotkeys,
    keyshortcuts,
    noty
  ) {
    var self = this;
    self.dataLevel = "dataset";
    var s_accession = $stateParams.s_accession;
    self.resourceExists = true;

    self.flowOptionsResources = function () {
      return {
        target: apiUrl + "/study/" + s_accession + "/resources/upload",
        chunkSize: 10 * 1024 * 1024,
        simultaneousUploads: 1,
        testChunks: false,
        permanentErrors: [401, 405, 500, 501],
        // withCredentials: true,
        headers: { Authorization: "Bearer " + $auth.getToken() },
      };
    };
    self.uploadFileError = function ($file, $message, $flow) {
      // $log.error("Upload file error");
      // $log.error($file)
      // $log.error($message)
    };
    self.loadStudyInfo = function () {
      return DataService.getStudyInfo(s_accession).then(
        function (out_data) {
          if (out_data.elements == 0) {
            self.resourceExists = false;
          }
          self.studyInfo = out_data.data[0];
          var owner = self.studyInfo._ownership[0].email;
          noty.extractErrors(out_data, noty.WARNING);
          return true;
        },
        function (out_data) {
          self.resourceExists = false;
          noty.extractErrors(out_data, noty.ERROR);
          return false;
        }
      );
    };

    self.loadDatasets = function () {
      self.loadingDatasets = true;
      DataService.getDatasets(s_accession).then(function (out_data) {
        self.datasets = out_data.data;
        self.datasetsCount = out_data.data.length;
        self.loadingDatasets = false;

        self.access = [];
        var promises = [];
        for (var i = 0; i < self.datasets.length; i++) {
          var id = self.datasets[i].accession;
          var d = self.datasets[i];
          self.access[id] = [];
          self.access[id]["loading"] = 1;
          var promise = DataService.getDatasetAccess(d.accession);

          promises.push(promise);
        }
        $q.all(promises).then(
          function (out_data) {
            for (var i = 0; i < out_data.length; i++) {
              var data = out_data[i].data;
              var id = data[0].dataset;
              self.access[id]["access"] = data;
              self.access[id]["loading"] = 0;
            }
            noty.extractErrors(out_data, noty.WARNING);
          },
          function (out_data) {
            noty.extractErrors(out_data, noty.ERROR);
          }
        );
      });
    };

    self.getBatchOperations = function () {
      // self.loadingStudies = true;
      DataService.getBatchOperations(s_accession).then(
        function (out_data) {
          self.batch_operations = out_data.data;
          // self.loadingStudies = false;
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          // self.loadingStudies = false;
          self.studyCount = 0;

          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };
    self.getBatchOperations();

    self.loadStudyInfo().then(function (ok) {
      if (ok) {
        self.loadDatasets();
        self.loadSamples();
        self.loadPhenotypes();
        self.loadTechnicalMetadata();
        self.loadResources();
      }
    });

    self.setData2Datasets = function () {
      var promises = [];

      for (var i = 0; i < self.datasets.length; i++) {
        if (!self.datasets[i].isSelected) continue;

        var promise = DataService.assignMeta2Dataset(
          self.datasets[i].accession,
          self.setSample,
          self.setPhenotype,
          self.setTechnicalMetadata
        );
        promises.push(promise);

        self.datasets[i].isSelected = false;
      }
      $q.all(promises).then(
        function (out_data) {
          $log.debug("Pushed all updates");
          self.loadDatasets();
          noty.extractErrors(out_data, noty.WARNINGS);
        },
        function (out_data) {
          noty.extractErrors(out_data, noty.ERROR);
        }
      );

      delete self.setSample;
      delete self.setPhenotype;
      delete self.setTechnicalMetadata;
    };

    self.undoData2Datasets = function () {
      for (var i = 0; i < self.datasets.length; i++) {
        self.datasets[i].isSelected = false;
      }

      delete self.setSample;
      delete self.setPhenotype;
      delete self.setTechnicalMetadata;
    };

    self.deleteDatasets = function (listctrl) {
      var text = "Are you really sure you want to delete selected datasets?";
      var subtext = "This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function () {
          var promises = [];

          for (var i = 0; i < self.datasets.length; i++) {
            if (!self.datasets[i].isSelected) continue;

            var promise = DataService.deleteDataset(self.datasets[i].accession);
            promises.push(promise);
          }
          listctrl.selectedElements = 0;

          $q.all(promises).then(
            function (out_data) {
              $log.debug("Dataset(s) removed");
              noty.showWarning("Dataset(s) successfully removed.");
              self.loadDatasets();
              noty.extractErrors(out_data, noty.WARNINGS);
            },
            function (out_data) {
              noty.extractErrors(out_data, noty.ERROR);
            }
          );
        },
        function () {}
      );
    };

    self.deleteSampleAssociation = function (accession) {
      var text = "Remove the association with this sample?";
      var subtext =
        "This dataset will no longer be associated with this sample. This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function () {
          var data = {};
          return DataService.assignMeta2Dataset(
            accession,
            -1,
            undefined,
            undefined
          ).then(
            function (out_data) {
              $log.debug("Sample association removed");
              noty.showWarning("Sample association removed.");
              self.loadDatasets();
              noty.extractErrors(out_data, noty.WARNING);
              return true;
            },
            function (out_data) {
              noty.extractErrors(out_data, noty.ERROR);
              return false;
            }
          );
        },
        function () {
          return false;
        }
      );
    };

    self.deletePhenotypeAssociation = function (accession) {
      var text = "Remove the association with this phenotype?";
      var subtext =
        "This dataset will no longer be associated with this phenotype. This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function () {
          var data = {};
          return DataService.assignMeta2Dataset(
            accession,
            undefined,
            -1,
            undefined
          ).then(
            function (out_data) {
              $log.debug("Phenotype association removed");
              noty.showWarning("Phenotype association removed.");
              self.loadDatasets();
              noty.extractErrors(out_data, noty.WARNING);
              return true;
            },
            function (out_data) {
              noty.extractErrors(out_data, noty.ERROR);
              return false;
            }
          );
        },
        function () {
          return false;
        }
      );
    };

    self.deleteTechnicalsAssociation = function (accession) {
      var text = "Remove the association with this set of technical metadata?";
      var subtext =
        "This dataset will no longer be associated with this set of technical metadata. This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function () {
          var data = {};
          return DataService.assignMeta2Dataset(
            accession,
            undefined,
            undefined,
            -1
          ).then(
            function (out_data) {
              $log.debug("Technical metadata association removed");
              noty.showWarning("Technical metadata association removed.");
              self.loadDatasets();
              noty.extractErrors(out_data, noty.WARNING);
              return true;
            },
            function (out_data) {
              noty.extractErrors(out_data, noty.ERROR);
              return false;
            }
          );
        },
        function () {
          return false;
        }
      );
    };

    self.showNewDataset = function (key, stagectrl) {
      FormDialogService.showFormlyDialog("", DatasetDialogController).then(
        function (answer) {
          noty.showSuccess("Dataset successfully created.");
          self.loadDatasets();

          if (!angular.isUndefined(stagectrl))
            stagectrl.assign_stage_files[key] = answer.accession;
        },
        function () {
          if (!angular.isUndefined(stagectrl))
            delete stagectrl.assign_stage_files[key];
        }
      );
    };

    self.updateDataset = function (dataset) {
      FormDialogService.showFormlyDialog(dataset, DatasetDialogController).then(
        function (answer) {
          noty.showSuccess("Dataset successfully modified.");
          self.loadDatasets();
        },
        function () {}
      );
    };

    // self.shareDataset = function(accession) {
    // 	showDialogWithData(
    // 		"share_dataset.html",
    // 		$event, $mdDialog, $mdMedia, accession
    // 	).then(function(answer) {
    //    		noty.showSuccess("Dataset successfully shared.");
    // 		self.loadDatasets();
    // 	}, function() {

    // 	});
    // }
    self.updateDatasetSelection = function (key, value, stagectrl) {
      if (value == -1) {
        self.showNewDataset(key, stagectrl);
      }
    };

    // SAMPLES
    self.samples = [];
    self.loadSamples = function () {
      self.loadingSamples = true;
      DataService.getSamples(s_accession).then(
        function (out_data) {
          self.samples = out_data.data;
          self.loadingSamples = false;
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          self.loadingSamples = false;
          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };

    self.showNewSample = function () {
      FormDialogService.showFormlyDialog("", SampleDialogController).then(
        function (answer) {
          noty.showSuccess("Sample successfully created.");
          self.loadSamples();
          self.setSample = answer.accession;
        },
        function () {
          self.setSample = "";
        }
      );
    };

    self.updateSample = function (data) {
      FormDialogService.showFormlyDialog(data, SampleDialogController).then(
        function (answer) {
          noty.showSuccess("Sample successfully modified.");
          self.loadSamples();
        },
        function () {}
      );
    };

    self.updateSampleSelection = function () {
      if (self.setSample == -1) {
        self.showNewSample();
      }
    };

    self.deleteSample = function (accession, ev) {
      var text = "Are you really sure you want to delete this sample?";
      var subtext = "This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function () {
          DataService.deleteSample(accession).then(
            function (out_data) {
              $log.debug("Sample removed");
              noty.showWarning("Sample successfully deleted.");
              self.loadDatasets();
              self.loadSamples();
              noty.extractErrors(out_data, noty.WARNING);
            },
            function (out_data) {
              noty.extractErrors(out_data, noty.ERROR);
            }
          );
        },
        function () {}
      );
    };

    // PHENOTYPES
    self.phenotypes = [];
    self.loadPhenotypes = function () {
      self.loadingPhenotypes = true;
      DataService.getPhenotypes(s_accession).then(
        function (out_data) {
          self.phenotypes = out_data.data;
          self.loadingPhenotypes = false;
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          self.loadingPhenotypes = false;
          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };

    self.showNewPhenotype = function () {
      FormDialogService.showFormlyDialog("", PhenotypeDialogController).then(
        function (answer) {
          noty.showSuccess("Phenotype successfully created.");
          self.loadPhenotypes();
          self.setPhenotype = answer.accession;
        },
        function () {
          self.setPhenotype = "";
        }
      );
    };

    self.updatePhenotype = function (data) {
      // var info = []
      // angular.copy(data, info)
      // if (info._birth_place && info._birth_place[0]) {
      // 	info['birth_place'] = info._birth_place[0].id
      // 	// info['country'] = info._birth_place[0].country
      // 	// info['region'] = info._birth_place[0].region
      // 	// info['city'] = info._birth_place[0].city
      // }

      FormDialogService.showFormlyDialog(data, PhenotypeDialogController).then(
        function (answer) {
          noty.showSuccess("Phenotype successfully modified.");
          self.loadPhenotypes();
        },
        function () {}
      );
    };

    self.updatePhenotypeSelection = function () {
      if (self.setPhenotype == -1) {
        self.showNewPhenotype();
      }
    };

    self.deletePhenotype = function (accession, ev) {
      var text = "Are you really sure you want to delete this phenotype?";
      var subtext = "This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function () {
          DataService.deletePhenotype(accession).then(
            function (out_data) {
              $log.debug("Phenotype removed");
              noty.showWarning("Phenotype successfully removed.");
              self.loadDatasets();
              self.loadPhenotypes();
              noty.extractErrors(out_data, noty.WARNING);
            },
            function (out_data) {
              noty.extractErrors(out_data, noty.ERROR);
            }
          );
        },
        function () {}
      );
    };

    // TECHNICAL METADATA

    self.loadTechnicalMetadata = function () {
      self.loadingTechnicalMetadata = true;
      DataService.getTechnicalMetadata(s_accession).then(
        function (out_data) {
          self.technicalmeta = out_data.data;
          self.loadingTechnicalMetadata = false;
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          self.loadingTechnicalMetadata = false;
          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };

    self.showNewTechnicalMetadata = function () {
      FormDialogService.showFormlyDialog("", TechnicalDialogController).then(
        function (answer) {
          noty.showSuccess("Technical metadata successfully created.");
          self.loadTechnicalMetadata();
          self.setTechnicalMetadata = answer.accession;
        },
        function () {
          self.setTechnicalMetadata = "";
        }
      );
    };

    self.updateTechnicalMetadata = function (data) {
      FormDialogService.showFormlyDialog(data, TechnicalDialogController).then(
        function (answer) {
          noty.showSuccess("Technical metadata successfully modified.");
          self.loadTechnicalMetadata();
        },
        function () {}
      );
    };

    self.updateTechnicalMetadataSelection = function () {
      if (self.setTechnicalMetadata == -1) {
        self.showNewTechnicalMetadata();
      }
    };

    self.deleteTechnicalMetadata = function (accession, ev) {
      var text =
        "Are you really sure you want to delete this set of technical metadata?";
      var subtext = "This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function () {
          DataService.deleteTechnicalMetadata(accession).then(
            function (out_data) {
              $log.debug("Technical Metadata removed");
              noty.showWarning("Technical metadata successfully removed.");
              self.loadDatasets();
              self.loadTechnicalMetadata();
              noty.extractErrors(out_data, noty.WARNING);
            },
            function (out_data) {
              noty.extractErrors(out_data, noty.ERROR);
            }
          );
        },
        function () {}
      );
    };

    // RESOURCES
    self.resources = [];
    self.loadResources = function () {
      self.loadingResources = true;
      self.resourcesCount = 0;
      DataService.getResources(s_accession).then(
        function (out_data) {
          self.resources = out_data.data;
          self.loadingResources = false;
          // self.resourcesCount = Object.keys(self.resources).length;
          self.resourcesCount = self.resources.length;
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          self.loadingResources = false;
          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };

    self.deleteResource = function (accession, ev) {
      var text = "Are you really sure you want to delete this resource?";
      var subtext =
        "This operation cannot be undone and also linked data will be removed";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function () {
          DataService.deleteResource(accession).then(
            function (out_data) {
              $log.debug("Resource removed");
              noty.showWarning("Resource successfully removed.");
              self.loadResources();
              self.getBatchOperations();
              noty.extractErrors(out_data, noty.WARNING);
            },
            function (out_data) {
              noty.extractErrors(out_data, noty.ERROR);
            }
          );
        },
        function () {}
      );
    };

    self.reimport = function (accession) {
      DataService.reimport(accession).then(
        function (out_data) {
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };

    /* Hotkeys configuration --- TEST */
    // hotkeys.bindTo($scope)
    // 	.add({
    // 		combo: "down",
    // 		description: "Scroll down along the list of datasets",
    // 		callback: function() {
    // 			keyshortcuts.scrollListDown(event, self, self.datasets);
    // 		}
    // 	}).add({
    // 		combo: "up",
    // 		description: "Scroll up along the list of datasets",
    // 		callback: function() {
    // 			keyshortcuts.scrollListUp(event, self, self.datasets);
    // 		}
    // 	}).add({
    // 		combo: "enter",
    // 		description: "Open a datasets",
    // 		callback: function() {
    // 			var accession = keyshortcuts.getSelectedID(self, self.datasets);
    // 			keyshortcuts.openEntry(event, self, $state,
    // 						"logged.study.datasets.files",
    // 						{s_accession: s_accession, d_accession: accession});
    // 		}
    // 	}).add({
    // 		combo: "space",
    // 		description: "Select a dataset",
    // 		callback: function() {
    // 			keyshortcuts.selectElement(event, self);
    // 		}
    // 	});
  }

  function ShareDataset($scope, DataService, noty) {
    var self = this;
    this.save = function () {
      var d_accession = $scope.data;

      var promise = DataService.shareDataset(d_accession, self.email);

      promise.then(
        function (out_data) {
          $scope.answer(out_data.data);
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };
  }

  function DatasetDialogController(
    $scope,
    $controller,
    $uibModalInstance,
    $log,
    $stateParams,
    DataService,
    noty
  ) {
    $controller("FormlyDialogController", { $scope: $scope });
    // ! IMPORTANT !
    $scope.initParent($uibModalInstance);
    var form_data = $scope.form_data;
    var s_accession = $stateParams.s_accession;

    if (!form_data) {
      $scope.dialogTitle = "Create new dataset";
      $scope.buttonText = "Save";
    } else {
      $scope.dialogTitle = "Update dataset";
      $scope.buttonText = "Update";
    }
    $scope.createForm(DataService.getDatasetSchema(s_accession), form_data);

    $scope.save = function () {
      if (!$scope.formIsValid()) return false;

      var promise;
      if (form_data && form_data.accession)
        promise = DataService.updateDataset(form_data.accession, $scope.model);
      else {
        promise = DataService.saveDataset(s_accession, $scope.model);
      }

      return $scope.closeDialog(promise);
    };
  }

  function SampleDialogController(
    $scope,
    $controller,
    $uibModalInstance,
    $log,
    $stateParams,
    DataService,
    noty
  ) {
    $controller("FormlyDialogController", { $scope: $scope });
    // ! IMPORTANT !
    $scope.initParent($uibModalInstance);
    var form_data = $scope.form_data;
    var s_accession = $stateParams.s_accession;

    if (!form_data) {
      $scope.dialogTitle = "Create new sample";
      $scope.buttonText = "Save";
    } else {
      $scope.dialogTitle = "Update sample";
      $scope.buttonText = "Update";
    }
    $scope.createForm(DataService.getSampleSchema(s_accession), form_data);

    $scope.save = function () {
      if (!$scope.formIsValid()) return false;

      var promise;
      if (form_data && form_data.accession)
        promise = DataService.updateSample(form_data.accession, $scope.model);
      else {
        promise = DataService.saveSample(s_accession, $scope.model);
      }

      return $scope.closeDialog(promise);
    };
  }

  function AutocompletePhenotypeController($scope, $log, DataService) {
    var self = this;

    // self.newElement = function(element) {
    //   alert("Sorry! Not implemented " + element);
    // }

    self.querySearch = function (type, query) {
      if (type == "birthplace") return self.birthplace_querySearch(query);
      else if (type == "HPO") return self.HPO_querySearch(query);
      else {
        $log.error(
          "Type (" + type + ") not found in AutocompletePhenotypeController"
        );
      }
    };

    self.birthplace_querySearch = function (query) {
      return DataService.getPlaceOfBirth(query).then(
        function (out_data) {
          return out_data.data;
        },
        function (out_data) {
          return [];
        }
      );
    };

    self.HPO_querySearch = function (query) {
      return DataService.getHPO(query).then(
        function (out_data) {
          return out_data.data;
        },
        function (out_data) {
          return [];
        }
      );
    };
  }

  function PhenotypeDialogController(
    $scope,
    $controller,
    $uibModalInstance,
    $log,
    $stateParams,
    DataService,
    noty
  ) {
    $controller("FormlyDialogController", { $scope: $scope });
    // ! IMPORTANT !
    $scope.initParent($uibModalInstance);
    var form_data = $scope.form_data;
    var s_accession = $stateParams.s_accession;

    if (!form_data) {
      $scope.dialogTitle = "Create new phenotype";
      $scope.buttonText = "Save";
    } else {
      $scope.dialogTitle = "Update phenotype";
      $scope.buttonText = "Update";
    }
    $scope.createForm(
      DataService.getPhenotypeSchema(s_accession),
      form_data,
      "AutocompletePhenotypeController"
    );

    $scope.save = function () {
      if (!$scope.formIsValid()) return false;

      var promise;
      if (form_data && form_data.accession)
        promise = DataService.updatePhenotype(
          form_data.accession,
          $scope.model
        );
      else {
        promise = DataService.savePhenotype(s_accession, $scope.model);
      }

      return $scope.closeDialog(promise);
    };
  }

  function AutocompleteTechnicalController($scope, $log, DataService) {
    var self = this;

    // self.newElement = function(element) {
    //   alert("Sorry! Not implemented " + element);
    // }

    self.querySearch = function (type, query) {
      if (type == "enrichment_kit")
        return self.enrichment_kit_querySearch(query);
      else {
        $log.error(
          "Type (" + type + ") not found in AutocompleteTechnicalController"
        );
      }
    };

    self.enrichment_kit_querySearch = function (query) {
      return DataService.getEnrichmentKit(query).then(
        function (out_data) {
          return out_data.data;
        },
        function (out_data) {
          return [];
        }
      );
    };
  }

  function TechnicalDialogController(
    $scope,
    $controller,
    $uibModalInstance,
    $log,
    $stateParams,
    DataService,
    noty
  ) {
    $controller("FormlyDialogController", { $scope: $scope });
    // ! IMPORTANT !
    $scope.initParent($uibModalInstance);
    var form_data = $scope.form_data;
    var s_accession = $stateParams.s_accession;

    if (!form_data) {
      $scope.dialogTitle = "Create new set of technical metadata";
      $scope.buttonText = "Save";
    } else {
      $scope.dialogTitle = "Update technical metadata";
      $scope.buttonText = "Update";
    }
    $scope.createForm(
      DataService.getTechnicalMetadataSchema(s_accession),
      form_data,
      "AutocompleteTechnicalController"
    );

    $scope.save = function () {
      if (!$scope.formIsValid()) return false;

      var promise;
      if (form_data && form_data.accession)
        promise = DataService.updateTechnicalMetadata(
          form_data.accession,
          $scope.model
        );
      else {
        promise = DataService.saveTechnicalMetadata(s_accession, $scope.model);
      }

      return $scope.closeDialog(promise);
    };
  }
})();
