import { Component, Injector, Input } from "@angular/core";
import { DataService } from "@app/services/data.service";
import { BasePaginationComponent } from "@rapydo/components/base.pagination.component";
import { Dataset } from "@app/types";

@Component({
  selector: "nig-datasets",
  templateUrl: "./datasets.component.html"
})
export class DatasetsComponent extends BasePaginationComponent<Dataset> {
	@Input() studyUUID;

	constructor(
		protected injector: Injector
	) {
		super(injector);
	}

	ngOnInit() {
		this.init("Dataset", `study/${this.studyUUID}/datasets`, "Datasets");
		this.set_resource_endpoint("dataset");
	    this.initPaging(20, false);
	    this.list();
	}

}