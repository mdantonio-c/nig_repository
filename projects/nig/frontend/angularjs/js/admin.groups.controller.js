(function () {
  "use strict";

  angular.module("web").controller("GroupsController", GroupsController);
  angular
    .module("web")
    .controller("GroupDialogController", GroupDialogController);

  function GroupsController(
    $scope,
    $log,
    DataService,
    noty,
    FormDialogService
  ) {
    var self = this;

    self.loadGroups = function () {
      self.loading = true;
      self.groups = [];
      DataService.getGroups().then(
        function (out_data) {
          self.loading = false;
          self.groups = out_data.data;
          noty.extractErrors(out_data, noty.WARNING);
        },
        function (out_data) {
          noty.extractErrors(out_data, noty.ERROR);
        }
      );
    };

    self.loadGroups();

    self.updateGroup = function (group, $event) {
      FormDialogService.showFormlyDialog(group, GroupDialogController).then(
        function (answer) {
          noty.showSuccess("Group successfully updated.");
          self.loadGroups();
        },
        function () {}
      );
    };

    self.addNewGroup = function ($event) {
      FormDialogService.showFormlyDialog("", GroupDialogController).then(
        function (answer) {
          noty.showSuccess("Group successfully created.");
          self.loadGroups();
        },
        function () {}
      );
    };

    self.deleteGroup = function (group_id, ev) {
      var text = "Are you really sure you want to delete this group?";
      var subtext = "This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function (answer) {
          DataService.deleteGroup(group_id).then(
            function (out_data) {
              $log.debug("group removed");
              noty.showWarning("Group successfully deleted.");
              self.loadGroups();
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

  function GroupDialogController(
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
      $scope.dialogTitle = "Create new group";
      $scope.buttonText = "Save";
    } else {
      $scope.dialogTitle = "Update group";
      $scope.buttonText = "Update";
    }

    $scope.createForm(DataService.getGroupSchema(), form_data);

    $scope.save = function () {
      if (!$scope.formIsValid()) return false;

      var promise;
      if (form_data && form_data.id)
        promise = DataService.updateGroup(form_data.id, $scope.model);
      else promise = DataService.saveGroup($scope.model);

      return $scope.closeDialog(promise);
    };
  }
})();
