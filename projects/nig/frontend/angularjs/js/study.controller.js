(function () {
  "use strict";

  angular.module("web").controller("StudyController", StudyController);
  angular
    .module("web")
    .controller("StudyDialogController", StudyDialogController);

  function StudyController(
    $scope,
    $log,
    $q,
    $state,
    DataService,
    FormDialogService,
    hotkeys,
    keyshortcuts,
    noty
  ) {
    var self = this;
    self.dataLevel = "study";

    self.loadStudies = function () {
      self.loadingStudies = true;
      DataService.getStudies().then(
        function (out_data) {
          self.studies = out_data.data;
          self.studyCount = out_data.data.length;

          for (var i = 0; i < self.studyCount; i++) {
            var owner = self.studies[i]._ownership[0].email;
            self.studies[i]["readonly"] = owner != $scope.profile.email;
          }
          self.loadingStudies = false;

          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          self.loadingStudies = false;
          self.studyCount = 0;

          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };

    self.loadStudies();

    self.updateStudy = function (data) {
      FormDialogService.showFormlyDialog(data, StudyDialogController).then(
        function (answer) {
          noty.showSuccess("Study successfully updated.");
          self.loadStudies();
        },
        function () {}
      );
    };

    self.showNewStudy = function ($event) {
      FormDialogService.showFormlyDialog("", StudyDialogController).then(
        function (answer) {
          noty.showSuccess("Study successfully created.");
          self.loadStudies();
        },
        function () {}
      );
    };

    self.deleteStudy = function (s_accession, ev) {
      var text = "Are you really sure you want to delete this study?";
      var subtext = "This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function (answer) {
          DataService.deleteStudy(s_accession).then(
            function (out_data) {
              $log.debug("Study removed");
              self.loadStudies();
              noty.showWarning("Study successfully deleted.");
            },
            function (out_data) {
              noty.extractErrors(out_data, noty.ERROR);
            }
          );
        },
        function () {}
      );
    };
    self.deleteStudies = function (listctrl, ev) {
      var text = "Are you really sure you want to delete selected studies?";
      var subtext = "This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function () {
          var promises = [];

          for (var i = 0; i < self.studies.length; i++) {
            if (!self.studies[i].isSelected) continue;

            var promise = DataService.deleteStudy(self.studies[i].accession);
            promises.push(promise);
          }
          listctrl.selectedElements = 0;

          $q.all(promises).then(
            function (out_data) {
              $log.debug("Studies removed");
              self.loadStudies();
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

    /* Hotkeys configuration */
    // hotkeys.bindTo($scope)
    // 	.add({
    // 		combo: "down",
    // 		description: "Scroll down along the list of studies",
    // 		callback: function() {
    // 			keyshortcuts.scrollListDown(event, self, self.studies);
    // 		}
    // 	}).add({
    // 		combo: "up",
    // 		description: "Scroll up along the list of studies",
    // 		callback: function() {
    // 			keyshortcuts.scrollListUp(event, self, self.studies);
    // 		}
    // 	}).add({
    // 		combo: "enter",
    // 		description: "Open the selected study",
    // 		callback: function() {
    // 			var accession = keyshortcuts.getSelectedID(self, self.studies);
    // 			keyshortcuts.openEntry(event, self, $state, "logged.study.datasets", {s_accession: accession});
    // 		}
    // 	});
  }

  function StudyDialogController(
    $scope,
    $controller,
    $uibModalInstance,
    $log,
    DataService,
    noty
  ) {
    $controller("FormlyDialogController", { $scope: $scope });
    // ! IMPORTANT !
    $scope.initParent($uibModalInstance);
    var form_data = $scope.form_data;

    if (!form_data) {
      $scope.dialogTitle = "Create new study";
      $scope.buttonText = "Save";
    } else {
      $scope.dialogTitle = "Update study";
      $scope.buttonText = "Update";
    }

    $scope.createForm(DataService.getStudySchema(), form_data);

    $scope.save = function () {
      if (!$scope.formIsValid()) return false;

      var promise;
      if (form_data && form_data.accession)
        promise = DataService.updateStudy(form_data.accession, $scope.model);
      else promise = DataService.saveStudy($scope.model);

      return $scope.closeDialog(promise);
    };
  }
})();
