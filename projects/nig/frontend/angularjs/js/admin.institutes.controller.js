(function () {
  "use strict";

  angular
    .module("web")
    .controller("InstitutesController", InstitutesController);
  angular
    .module("web")
    .controller("InstituteDialogController", InstituteDialogController);

  function InstitutesController(
    $scope,
    $log,
    DataService,
    noty,
    FormDialogService
  ) {
    var self = this;

    self.loadInstitutes = function () {
      self.loading = true;
      self.institutes = [];
      DataService.getInstitutes().then(
        function (out_data) {
          self.loading = false;
          self.institutes = out_data.data;
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };

    self.loadInstitutes();

    self.updateInstitute = function (institute, $event) {
      FormDialogService.showFormlyDialog(
        institute,
        InstituteDialogController
      ).then(
        function (answer) {
          noty.showSuccess("Institute successfully updated.");
          self.loadInstitutes();
        },
        function () {}
      );
    };

    self.addNewInstitute = function ($event) {
      FormDialogService.showFormlyDialog("", InstituteDialogController).then(
        function (answer) {
          noty.showSuccess("Institute successfully created.");
          self.loadInstitutes();
        },
        function () {}
      );
    };

    self.deleteInstitute = function (institute_id, ev) {
      var text = "Are you really sure you want to delete this institute?";
      var subtext = "This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function (answer) {
          DataService.deleteInstitute(institute_id).then(
            function (out_data) {
              $log.debug("Institute removed");
              noty.showWarning("Institute successfully deleted.");
              self.loadInstitutes();
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
  }

  function InstituteDialogController(
    $scope,
    $controller,
    $log,
    $uibModalInstance,
    DataService,
    noty
  ) {
    $controller("FormlyDialogController", { $scope: $scope });
    // ! IMPORTANT !
    $scope.initParent($uibModalInstance);
    var form_data = $scope.form_data;

    if (!form_data) {
      $scope.dialogTitle = "Create new institute";
      $scope.buttonText = "Save";
    } else {
      $scope.dialogTitle = "Update institute";
      $scope.buttonText = "Update";
    }

    $scope.createForm(DataService.getInstituteSchema(), form_data);

    $scope.save = function () {
      if (!$scope.formIsValid()) return false;

      var promise;
      if (form_data && form_data.id)
        promise = DataService.updateInstitute(form_data.id, $scope.model);
      else promise = DataService.saveInstitute($scope.model);

      return $scope.closeDialog(promise);
    };
  }
})();
