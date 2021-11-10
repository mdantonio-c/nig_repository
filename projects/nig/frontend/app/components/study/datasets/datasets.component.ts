import { Component, Injector, Input } from "@angular/core";
import { DataService } from "@app/services/data.service";
import { BasePaginationComponent } from "@rapydo/components/base.pagination.component";
import { Dataset } from "@app/types";

@Component({
  selector: "nig-datasets",
  templateUrl: "./datasets.component.html",
  // styleUrls:["./datasets.component.css"],
})
export class DatasetsComponent extends BasePaginationComponent<Dataset> {
  @Input() studyUUID;
  expanded: any = {};

  constructor(protected injector: Injector, private dataService: DataService) {
    super(injector);
  }

  ngOnInit() {
    this.init("Dataset", `/api/study/${this.studyUUID}/datasets`, "Datasets");
    this.set_resource_endpoint("/api/dataset");
    this.initPaging(20, false);
    this.list();
  }

  toggleExpandRow(row) {
    this.table.rowDetail.toggleExpandRow(row);
  }

  onDetailToggle(event) {
    // console.log('File Panel Toggled', event);
  }

  setUploadReady(row) {
    if (!row.status) {
      row.uploadReady = true;
      return false;
    } else {
      row.uploadReady = false;
      return true;
    }
  }

  onUploadReadyChange(row, event) {
    this.dataService.sendUploadReady(row.uuid, row.uploadReady).subscribe(
      (resp) => {
        this.list();
        console.log(row.status);
      },
      (error) => {
        this.notify.showError(error);
        event.target.checked = !event.target.checked;
      }
    );
  }
}
