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
	/*columns = [
	  { prop: 'name' },
	  { prop: 'description' },
	  { prop: 'files', sortable: false },
	  { prop: 'technicals', name: 'Metadata', sortable: false }
	];*/

	constructor(
		protected injector: Injector
	) {
		super(injector);
	}

	ngOnInit() {
		this.init("datasets", `study/${this.studyUUID}/datasets`, "Datasets");
	    this.initPaging(20, false);
	    this.list();
	}

}