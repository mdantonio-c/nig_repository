(function () {
  "use strict";

  angular.module("web").controller("PhenotypeController", PhenotypeController);
  function PhenotypeController(
    $scope,
    $log,
    $q,
    FormDialogService,
    DataService,
    noty
  ) {
    var self = this;

    self.saveRelationship = function (datactrl, $event) {
      if (
        typeof self.parent1 !== "undefined" &&
        typeof self.parent2 !== "undefined" &&
        typeof self.relation !== "undefined"
      ) {
        DataService.saveRelationship(
          datactrl.phenotypes[self.parent1].accession,
          datactrl.phenotypes[self.parent2].accession,
          self.relation
        ).then(
          function (out_data) {
            noty.showSuccess("Relationship successfully created.");
            datactrl.loadPhenotypes();
            noty.extractErrors(out_data, noty.WARNING);
          },
          function (out_data) {
            noty.extractErrors(out_data, noty.ERROR);
          }
        );
      }
    };

    self.deleteRelationship = function (
      datactrl,
      accession1,
      accession2,
      relation,
      $event
    ) {
      var text = "Are you really sure you want to delete this relationship?";
      var subtext = "This operation cannot be undone.";
      FormDialogService.showConfirmDialog(text, subtext).then(
        function () {
          return DataService.deleteRelationship(
            accession1,
            accession2,
            relation
          ).then(
            function (out_data) {
              $log.debug("Relationship removed");
              noty.showWarning("Relationship successfully removed.");
              datactrl.loadPhenotypes();
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
  }
})();
