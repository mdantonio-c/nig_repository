import { Component, Injector, Input } from "@angular/core";
import { DataService } from "../../../services/data.service";
import { BasePaginationComponent } from "@rapydo/components/base.pagination.component";
import { Dataset } from "@app/types";
import { Subject } from "rxjs";

@Component({
  selector: "nig-datasets",
  templateUrl: "./datasets.component.html",
  styleUrls: ["./datasets.component.css"],
})
export class DatasetsComponent extends BasePaginationComponent<Dataset> {
  @Input() studyUUID;
  expanded: any = {};
  user: any = {};

  constructor(protected injector: Injector, private dataService: DataService) {
    super(injector);
  }

  ngOnInit() {
    this.user = this.auth.getUser();
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

  resetDatasetStatus(datasetUuid) {
    this.dataService.sendUploadReady(datasetUuid, true).subscribe(
      (resp) => {
        this.list();
      },
      (error) => {
        this.notify.showError(error);
      }
    );
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
      },
      (error) => {
        this.notify.showError(error);
        event.target.checked = !event.target.checked;
      }
    );
  }

  list(): Subject<boolean> {
    const res$ = super.list();
    res$.subscribe(() => {
      this.dataService.changeCounter(this.data.length, "datasets");
    });
    return res$;
  }
}
