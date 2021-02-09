(function () {
  "use strict";

  angular.module("web").controller("StageController", StageController);

  function StageController(
    $scope,
    $q,
    $log,
    $state,
    $stateParams,
    DataService,
    noty
  ) {
    var self = this;
    if ($state.current.name == "logged.study.datasets") {
      self.dataLevel = "dataset";
    } else {
      self.dataLevel = "study";
    }

    self.assign_stage_files = {};
    self.stageLoaded = false;
    self.loadingStage = false;

    self.treeOptions = {
      nodeChildren: "objects",
      dirSelectable: false, // If false, clicking on the dir label will expand and contact the dir
      isLeaf: function (element) {
        return element.object_type != "collection";
      },
      injectClasses: {
        ul: "collection",
        li: "collection-item amber lighten-5",
        liSelected: "",
        iExpanded: "a3",
        iCollapsed: "a4",
        iLeaf: "a5",
        label: "a6",
        labelSelected: "a8",
      },
    };

    self.loadStage = function () {
      self.loadingStage = true;
      DataService.getStage().then(
        function (out_data) {
          self.stage = out_data.data;
          self.unparsedStageCount = Object.keys(self.stage).length;
          self.stageTree = stageTree(self.stage, self.dataLevel, true);
          self.stageCount = self.stageTree.length;

          self.loadingStage = false;
          self.stageLoaded = true;
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          self.loadingStage = false;
          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };

    // self.loadStage();

    self.assignFiles = function (datasetList, dataController) {
      var keys = null;
      var numElements = 0;
      if (!angular.isUndefined(self.assign_stage_files)) {
        keys = Object.keys(self.assign_stage_files);
        numElements = keys.length;
      }

      if (numElements == 0) {
        console.log("Empty selection: cannot assign any stage file");
        alert("Empty selection: cannot assign any stage file");
      } else {
        self.loadingStage = true;
        var promises = [];
        for (var i = 0; i < numElements; i++) {
          var file = keys[i];
          var d_accession = self.assign_stage_files[file];
          var fullFileName = file;
          if (fullFileName.charAt(0) == "/")
            fullFileName = fullFileName.substr(1);

          if (d_accession == -2) {
            var s_accession = dataController.studyInfo.accession;
            var promise = DataService.moveResource(fullFileName, s_accession);
          } else {
            var promise = DataService.moveStage(fullFileName, d_accession);
          }
          promises.push(promise);
        }
        $q.all(promises).then(
          function (out_data) {
            DataService.getStage().then(function (out_data) {
              self.stage = out_data.data;
              self.unparsedStageCount = Object.keys(self.stage).length;

              self.stageTree = stageTree(self.stage, self.dataLevel, true);
              self.stageCount = self.stageTree.length;

              self.loadingStage = false;
            });

            dataController.loadDatasets();
            dataController.loadResources();
            dataController.getBatchOperations();
            noty.extractErrors(out_data, noty.WARNING);
          },
          function (out_data) {
            noty.extractErrors(out_data, noty.ERROR);
          }
        );
        delete self.assign_stage_files;
      }
    };
    // BATCH IMPORT

    self.importStudy = function (collection, datactrl) {
      DataService.importStudy(collection.name).then(
        function (out_data) {
          console.log("Study imported");
          datactrl.loadStudies();
          self.loadStage();
          noty.showInfo(
            "Import of " +
              collection.name +
              " successfully started. It will proceed in background"
          );
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };

    self.importDataset = function (collection, datactrl) {
      var s_accession = datactrl.studyInfo.accession;
      DataService.importDataset(collection.name, s_accession).then(
        function (out_data) {
          console.log("Dataset imported");
          datactrl.loadDatasets();
          self.loadStage();
          noty.showInfo(
            "Import of " +
              collection.name +
              " successfully started. It will proceed in background"
          );
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };
  }

  var countFiles = function (list) {
    var files = 0;
    var dirs = 0;
    if (list.objects)
      for (var j = 0; j < list.objects.length; j++) {
        if (list.objects[j].object_type == "dataobject") {
          list.objects[j].schema = "file";
          files++;
        }
      }
    return files;
  };

  function stageTree(stage, dataLevel, rootLevel) {
    var tree = [];
    var keys = Object.keys(stage);
    var count = keys.length;
    for (var i = 0; i < count; i++) {
      var k = keys[i];
      var element = stage[k];

      if (element.object_type == "dataobject") {
        element.schema = "file";
      } else {
        element.objects = stageTree(element.objects, dataLevel, false);

        var files = countFiles(element);
        var dirs = element.objects.length - files;

        if (files == 0 && dirs == 0) {
          //remove empty directories from tree
          continue;
          element.schema = "empty";
        } else if (files > 0 && dirs == 0) {
          element.schema = "dataset";
          // } else if (files > 0  && dirs > 0) {
          // 	element.schema='mix';
          // } else if (files == 0 && dirs > 0) {
        } else if (dirs > 0) {
          //should be further expected
          var validDatasets = 0;
          var nfiles = 0;
          if (!angular.isUndefined(element.objects))
            nfiles = element.objects.length;
          for (var j = 0; j < nfiles; j++) {
            var c = countFiles(element.objects[j]);
            //No files contained into this dataset => not valid
            if (!element.objects[j].objects) continue;
            //No files contained into this dataset => not valid
            if (c <= 0) continue;
            //This dataset also contains other directories => not valid
            if (c != element.objects[j].objects.length) continue;
            validDatasets++;
          }
          if (validDatasets == nfiles - files) element.schema = "study";
          else element.schema = "mix";
        }
      }

      if (rootLevel) {
        if (dataLevel == "study") {
          if (element.schema == "dataset") continue;
          if (element.schema == "mix") continue;
          if (element.schema == "file") continue;
        } else if (dataLevel == "dataset") {
        }
      }

      tree.push(element);
    }

    return tree;
  }
})();
