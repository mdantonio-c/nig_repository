(function () {
  "use strict";

  angular.module("web").controller("FilesController", FilesController);

  function FilesController(
    $scope,
    $log,
    $state,
    $stateParams,
    $auth,
    DataService,
    noty
  ) {
    //$log.info("Files Controller");
    var self = this;
    $scope.data = {};
    self.resourceExists = true;

    self.flowOptionsResources = function () {
      return {
        target:
          apiUrl + "/dataset/" + $stateParams.d_accession + "/files/upload",
        chunkSize: 10 * 1024 * 1024,
        simultaneousUploads: 1,
        testChunks: false,
        permanentErrors: [401, 405, 500, 501],
        // withCredentials: true,
        headers: { Authorization: "Bearer " + $auth.getToken() },
      };
    };

    DataService.getFiles($stateParams.d_accession).then(
      function (out_data) {
        self.files = out_data.data;
        // self.filesCount = Object.keys(self.files).length;
        self.filesCount = self.files.length;
        noty.extractErrors(out_data, noty.WARNING);
      },
      function (out_data) {
        noty.extractErrors(out_data, noty.ERROR);
      }
    );

    DataService.getStudyInfo($stateParams.s_accession).then(
      function (out_data) {
        if (out_data.elements == 0) {
          self.resourceExists = false;
        }
        self.studyInfo = out_data.data[0];
        noty.extractErrors(out_data, noty.WARNING);
      },
      function (out_data) {
        self.resourceExists = false;
        noty.extractErrors(out_data, noty.ERROR);
      }
    );

    DataService.getDatasetInfo($stateParams.d_accession).then(
      function (out_data) {
        if (out_data.elements == 0) {
          self.resourceExists = false;
        }
        self.datasetInfo = out_data.data[0];
        noty.extractErrors(out_data, noty.WARNING);
      },
      function (out_data) {
        self.resourceExists = false;
        noty.extractErrors(out_data, noty.ERROR);
      }
    );

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
  }
})();
