(function () {
  "use strict";

  angular.module("web").service("keyshortcuts", HotkeysService);

  function HotkeysService() {
    var self = this;

    self.scrollListDown = function (event, controller, list) {
      event.preventDefault();
      if (isNaN(controller.focusPosition)) controller.focusPosition = 1;
      else if (controller.focusPosition < list.length)
        controller.focusPosition = controller.focusPosition + 1;
    };

    self.scrollListUp = function (event, controller, list) {
      event.preventDefault();
      if (isNaN(controller.focusPosition)) controller.focusPosition = 1;
      else if (controller.focusPosition > 0)
        controller.focusPosition = controller.focusPosition - 1;
    };

    self.getSelectedID = function (controller, list) {
      if (isNaN(controller.focusPosition)) return 0;
      return list[controller.focusPosition - 1].accession;
    };

    self.selectElement = function (event, controller, list) {
      if (isNaN(controller.focusPosition)) return false;
      controller.selectElement(list[controller.focusPosition - 1], controller);
      return true;
    };

    self.openEntry = function (
      event,
      controller,
      $state,
      newstateName,
      newstateParameters
    ) {
      event.preventDefault();
      if (isNaN(controller.focusPosition)) console.log("No entry selected");
      else {
        $state.go(newstateName, newstateParameters);
      }
    };

    self.openHistorySidebar = function (event, controller) {
      event.preventDefault();
      controller.open();
    };
  }
})();
