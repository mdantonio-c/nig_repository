(function () {
  "use strict";

  angular.module("web").controller("StatsController", StatsController);

  function StatsController($scope, $rootScope, $log, DataService, noty) {
    var self = this;

    DataService.getStats($rootScope.logged).then(
      function (out_data) {
        self.stats = out_data.data;
        // console.log(self.stats);
        noty.extractErrors(out_data, noty.WARNING);
      },
      function (out_data) {
        noty.extractErrors(out_data, noty.ERROR);
      }
    );
  }
})();
